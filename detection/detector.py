"""
VeriaChain — Module de détection VeriaDetect
============================================
Pipeline en deux étapes :
  1. Analyse fréquentielle & texture (scipy/numpy) — disponible hors ligne
  2. Inférence par modèle pré-entraîné HuggingFace (si disponible)

Le mode "ensemble" combine les deux scores pour un résultat plus robuste.
"""
from __future__ import annotations

import logging
import hashlib
import io
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DetectionMetrics:
    """Métriques intermédiaires de l'analyse fréquentielle."""
    fft_energy_ratio:  float = 0.0  # rapport énergie haute/basse fréquence
    edge_sharpness:    float = 0.0  # netteté des contours (Sobel)
    color_entropy:     float = 0.0  # entropie colorimétrique
    local_variance:    float = 0.0  # variance de texture locale
    noise_level:       float = 0.0  # niveau de bruit résiduel
    prnu_score:        float = 0.0  # score cohérence bruit capteur (approx.)


@dataclass
class DetectionResult:
    """Résultat complet de l'analyse d'une image."""
    ai_probability:   float           # 0.0 (authentique) → 1.0 (IA)
    confidence:       float           # 0.0 → 1.0
    label:            str             # libellé lisible
    label_en:         str             # English label for API
    metrics:          DetectionMetrics = field(default_factory=DetectionMetrics)
    model_score:      Optional[float] = None  # score du modèle HF si disponible
    freq_score:       float = 0.0             # score fréquentiel
    sha256:           str = ""
    file_size_kb:     int = 0
    resolution:       str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Frequency-based analysis
# ──────────────────────────────────────────────────────────────────────────────

class FrequencyAnalyzer:
    """
    Analyse spectrale et texturale d'une image.

    Fondements académiques :
    - Wang et al. 2020 (CNNDetection) : artefacts spectraux des GAN
    - Zhang et al. 2019 : analyse FFT des images synthétiques
    - Fridrich et al. 2012 : analyse PRNU pour l'authenticité forensique
    """

    TARGET_SIZE = 256

    def analyze(self, img: Image.Image) -> tuple[float, DetectionMetrics]:
        """Retourne un score IA [0,1] et les métriques détaillées."""
        img_rgb  = img.convert("RGB").resize((self.TARGET_SIZE, self.TARGET_SIZE), Image.LANCZOS)
        arr      = np.array(img_rgb, dtype=np.float32)

        metrics = DetectionMetrics(
            fft_energy_ratio = self._fft_energy_ratio(arr),
            edge_sharpness   = self._edge_sharpness(arr),
            color_entropy    = self._color_entropy(arr),
            local_variance   = self._local_variance(arr),
            noise_level      = self._noise_level(arr),
            prnu_score       = self._prnu_score(arr),
        )

        score = self._combine(metrics)
        return float(np.clip(score, 0.03, 0.97)), metrics

    # ── Spectral analysis ────────────────────────────────────────────────────

    def _fft_energy_ratio(self, arr: np.ndarray) -> float:
        """
        Rapport énergie haute fréquence / énergie basse fréquence.
        Les GAN et modèles de diffusion génèrent des régularités
        spectrales anormales détectables dans le domaine de Fourier.
        Référence : Zhang et al. 2019.
        """
        gray = arr.mean(axis=2)
        fft  = np.fft.fft2(gray)
        fft_shifted = np.fft.fftshift(fft)
        magnitude = np.abs(fft_shifted)

        h, w = magnitude.shape
        cy, cx = h // 2, w // 2
        radius_low  = min(h, w) // 8
        radius_high = min(h, w) // 4

        Y, X = np.ogrid[:h, :w]
        dist = np.sqrt((Y - cy)**2 + (X - cx)**2)

        low_energy  = magnitude[dist <= radius_low].sum()
        high_energy = magnitude[(dist > radius_high) & (dist <= radius_high * 2)].sum()

        if low_energy < 1e-6:
            return 0.5
        ratio = high_energy / (low_energy + high_energy)
        # AI images tend to have lower high-frequency content (smoother)
        # Normalize: very smooth (ratio ~ 0.2) → high AI score
        return float(np.clip(1.0 - ratio * 2.5, 0, 1))

    # ── Edge analysis ────────────────────────────────────────────────────────

    def _edge_sharpness(self, arr: np.ndarray) -> float:
        """
        Densité et netteté des contours via filtrage Sobel approximé.
        Les images IA ont souvent des contours trop lisses ou trop parfaits.
        """
        gray = arr.mean(axis=2)
        # Sobel X
        gy = np.diff(gray, axis=0, prepend=gray[:1])
        gx = np.diff(gray, axis=1, prepend=gray[:, :1])
        magnitude = np.sqrt(gx**2 + gy**2)
        mean_edge = float(magnitude.mean())

        # Very sharp edges → more likely authentic (real camera)
        # Too uniform edges → AI signal
        # Normalized: high sharpness → low AI score
        normalized = np.clip(mean_edge / 40.0, 0, 1)
        return float(1.0 - normalized)  # inverse: low sharpness → high score

    # ── Color entropy ────────────────────────────────────────────────────────

    def _color_entropy(self, arr: np.ndarray) -> float:
        """Entropie de la distribution colorimétrique par canal."""
        entropies = []
        for c in range(3):
            hist, _ = np.histogram(arr[:, :, c], bins=64, range=(0, 255))
            hist = hist / hist.sum()
            hist = hist[hist > 0]
            entropy = -np.sum(hist * np.log2(hist))
            entropies.append(entropy)
        avg_entropy = np.mean(entropies)
        # Very uniform color distribution → AI signal
        # Too high entropy → noisy → real camera signal
        # Optimal real photo: mid-range entropy (~3.5-4.5)
        if avg_entropy < 2.5:
            return 0.7  # too uniform → AI
        if avg_entropy > 5.0:
            return 0.2  # too noisy → probably real
        # Bell curve around 3.8 for real photos
        return float(np.clip(abs(avg_entropy - 3.8) / 2.0, 0, 1))

    # ── Texture analysis ─────────────────────────────────────────────────────

    def _local_variance(self, arr: np.ndarray) -> float:
        """
        Variance locale dans des patches 8×8.
        Textures trop lisses = signal IA (lissage excessif des GAN).
        """
        gray = arr.mean(axis=2)
        patch_size = 8
        variances = []
        for y in range(0, self.TARGET_SIZE - patch_size, patch_size):
            for x in range(0, self.TARGET_SIZE - patch_size, patch_size):
                patch = gray[y:y+patch_size, x:x+patch_size]
                variances.append(float(patch.var()))

        mean_var = np.mean(variances)
        # Very low local variance → too smooth → AI
        # Normalize: < 100 → high AI score
        return float(np.clip(1.0 - mean_var / 300.0, 0, 1))

    # ── Noise analysis ───────────────────────────────────────────────────────

    def _noise_level(self, arr: np.ndarray) -> float:
        """
        Estimation du bruit de capteur via différence avec version lissée.
        Les photos authentiques ont un bruit de capteur caractéristique.
        Les images IA ont un bruit trop régulier ou absent.
        """
        pil = Image.fromarray(arr.astype(np.uint8))
        smoothed = np.array(pil.filter(ImageFilter.GaussianBlur(radius=1)), dtype=np.float32)
        residual = np.abs(arr - smoothed)

        std_r = float(residual[:,:,0].std())
        std_g = float(residual[:,:,1].std())
        std_b = float(residual[:,:,2].std())
        noise = (std_r + std_g + std_b) / 3.0

        # Very low noise → AI (too clean)
        # Natural noise range: 2–8 for real cameras
        if noise < 1.5:
            return 0.75  # suspiciously clean → AI
        if noise > 10:
            return 0.15  # high noise → camera
        return float(np.clip(1.0 - noise / 8.0, 0, 1))

    # ── PRNU approximation ───────────────────────────────────────────────────

    def _prnu_score(self, arr: np.ndarray) -> float:
        """
        Approximation de la cohérence PRNU (Photo Response Non-Uniformity).
        Les vrais capteurs ont un bruit spatialement corrélé et cohérent.
        Référence : Fridrich et al. 2012 (Digital Image Forensics).
        """
        pil = Image.fromarray(arr.astype(np.uint8))
        smoothed = np.array(pil.filter(ImageFilter.GaussianBlur(radius=2)), dtype=np.float32)
        noise_map = arr - smoothed

        # Measure spatial autocorrelation in noise map
        gray_noise = noise_map.mean(axis=2)
        # Simple autocorrelation: compare with shifted version
        shift = 4
        correlation = float(np.corrcoef(
            gray_noise[:-shift, :-shift].flatten(),
            gray_noise[shift:, shift:].flatten()
        )[0, 1])

        # Real cameras: moderate positive correlation (~0.3–0.7)
        # AI images: very low or very high correlation
        if 0.2 < correlation < 0.6:
            return 0.2  # natural pattern → authentic
        return float(np.clip(1.0 - abs(correlation - 0.4) * 2, 0, 1))

    # ── Score combination ────────────────────────────────────────────────────

    def _combine(self, m: DetectionMetrics) -> float:
        """
        Combinaison pondérée des métriques.
        Pondérations calibrées sur le dataset de test du mémoire.
        """
        weights = {
            "fft_energy_ratio": 0.25,
            "local_variance":   0.22,
            "noise_level":      0.20,
            "edge_sharpness":   0.15,
            "prnu_score":       0.12,
            "color_entropy":    0.06,
        }
        score = (
            m.fft_energy_ratio  * weights["fft_energy_ratio"] +
            m.local_variance    * weights["local_variance"]   +
            m.noise_level       * weights["noise_level"]      +
            m.edge_sharpness    * weights["edge_sharpness"]   +
            m.prnu_score        * weights["prnu_score"]       +
            m.color_entropy     * weights["color_entropy"]
        )
        return float(score)


# ──────────────────────────────────────────────────────────────────────────────
# HuggingFace model loader
# ──────────────────────────────────────────────────────────────────────────────

class HuggingFaceDetector:
    """
    Détecteur basé sur le modèle umm-maybe/AI-image-detector,
    celui évalué au chapitre 10 du mémoire (533 images, dataset Hemg).
    Téléchargement automatique au premier lancement.
    """

    def __init__(self, model_id: str, cache_dir: Path):
        self.model_id  = model_id
        self.cache_dir = cache_dir
        self._pipeline = None

    def _load(self):
        if self._pipeline is not None:
            return
        try:
            from transformers import pipeline as hf_pipeline
            logger.info(f"Chargement du modèle {self.model_id} (peut prendre 30–60 s au premier lancement)…")
            self._pipeline = hf_pipeline(
                "image-classification",
                model=self.model_id,
                cache_dir=str(self.cache_dir),
                top_k=2,
            )
            logger.info("Modèle chargé.")
        except Exception as exc:
            logger.warning(f"Impossible de charger le modèle HuggingFace : {exc}")
            self._pipeline = None

    def predict(self, img: Image.Image) -> Optional[float]:
        """Retourne la probabilité IA [0,1] ou None si le modèle est indisponible."""
        self._load()
        if self._pipeline is None:
            return None
        try:
            results = self._pipeline(img.convert("RGB"))
            # Model labels: "Fake" / "Real" or "ai" / "real"
            for r in results:
                lbl = r["label"].lower()
                if any(k in lbl for k in ("fake", "ai", "artificial", "generated")):
                    return float(r["score"])
                if any(k in lbl for k in ("real", "authentic", "genuine")):
                    return float(1.0 - r["score"])
            return None
        except Exception as exc:
            logger.warning(f"Erreur d'inférence HuggingFace : {exc}")
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Main detector
# ──────────────────────────────────────────────────────────────────────────────

LABELS = [
    (0.15, "Authentique",            "Authentic",         "success"),
    (0.35, "Probablement authentique","Probably authentic","success"),
    (0.55, "Résultat incertain",      "Uncertain",         "warning"),
    (0.72, "Probablement IA",         "Probably AI",       "danger"),
    (1.00, "Très probablement IA",    "Very likely AI",    "danger"),
]


def _label(score: float) -> tuple[str, str, str]:
    for threshold, fr, en, cls in LABELS:
        if score <= threshold:
            return fr, en, cls
    return LABELS[-1][1], LABELS[-1][2], LABELS[-1][3]


class VeriaDetector:
    """Point d'entrée principal du module de détection."""

    def __init__(self, config):
        self.mode     = getattr(config, "DETECTION_MODE", "ensemble")
        self.freq_analyzer = FrequencyAnalyzer()
        self.hf_detector   = HuggingFaceDetector(
            model_id  = getattr(config, "HF_MODEL_ID", "umm-maybe/AI-image-detector"),
            cache_dir = Path(getattr(config, "MODEL_CACHE_DIR", "models")),
        )

    def analyze_image(self, image_bytes: bytes, filename: str = "") -> DetectionResult:
        """Analyse une image et retourne le résultat complet."""
        # Hash & metadata
        sha256      = hashlib.sha256(image_bytes).hexdigest()
        size_kb     = len(image_bytes) // 1024
        img         = Image.open(io.BytesIO(image_bytes))
        resolution  = f"{img.width}×{img.height} px"

        # Frequency analysis (always available)
        freq_score, metrics = self.freq_analyzer.analyze(img)

        # HuggingFace model (if available and mode includes it)
        model_score = None
        if self.mode in ("huggingface", "ensemble"):
            model_score = self.hf_detector.predict(img)

        # Combine scores
        if self.mode == "huggingface" and model_score is not None:
            final_score = model_score
        elif self.mode == "frequency" or model_score is None:
            final_score = freq_score
        else:  # ensemble
            # Weight: 65% model, 35% frequency
            final_score = 0.65 * model_score + 0.35 * freq_score

        final_score = float(np.clip(final_score, 0.02, 0.98))
        confidence  = float(abs(final_score - 0.5) * 2)
        label_fr, label_en, _ = _label(final_score)

        return DetectionResult(
            ai_probability = round(final_score, 4),
            confidence     = round(confidence, 4),
            label          = label_fr,
            label_en       = label_en,
            metrics        = metrics,
            model_score    = round(model_score, 4) if model_score is not None else None,
            freq_score     = round(freq_score, 4),
            sha256         = sha256,
            file_size_kb   = size_kb,
            resolution     = resolution,
        )

    def analyze_document(self, file_bytes: bytes, filename: str) -> dict:
        """
        Détection pour les documents (PDF, DOCX, TXT).
        Combine analyse textuelle (statistiques linguistiques) et
        analyse des images extraites du document.
        """
        ext = Path(filename).suffix.lower()
        results = {"filename": filename, "pages": [], "overall_ai_probability": 0.0}

        if ext == ".pdf":
            results.update(self._analyze_pdf(file_bytes))
        elif ext == ".docx":
            results.update(self._analyze_docx(file_bytes))
        elif ext in (".txt", ".eml", ".msg"):
            results.update(self._analyze_text(file_bytes.decode("utf-8", errors="replace")))
        else:
            results["error"] = f"Format non supporté : {ext}"

        return results

    def _analyze_pdf(self, pdf_bytes: bytes) -> dict:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_results = []
            image_scores = []

            for page_num, page in enumerate(doc, 1):
                # Extract text from page
                text = page.get_text()
                text_score = self._text_ai_score(text)

                # Extract and analyze images
                img_scores = []
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image["image"]
                    try:
                        res = self.analyze_image(img_bytes, f"page{page_num}_img.png")
                        img_scores.append(res.ai_probability)
                    except Exception:
                        pass

                page_ai = text_score if not img_scores else (
                    0.5 * text_score + 0.5 * float(np.mean(img_scores))
                )
                page_results.append({
                    "page": page_num,
                    "text_ai_score": round(text_score, 3),
                    "image_scores": [round(s, 3) for s in img_scores],
                    "page_ai_probability": round(page_ai, 3),
                })
                image_scores.append(page_ai)

            overall = float(np.mean(image_scores)) if image_scores else 0.5
            return {"pages": page_results, "overall_ai_probability": round(overall, 3)}
        except ImportError:
            return {"error": "PyMuPDF non installé. Lancez : pip install PyMuPDF"}
        except Exception as e:
            return {"error": str(e)}

    def _analyze_docx(self, docx_bytes: bytes) -> dict:
        try:
            from docx import Document
            import io as _io
            doc = Document(_io.BytesIO(docx_bytes))
            full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            score = self._text_ai_score(full_text)
            return {
                "pages": [{"page": 1, "text_ai_score": round(score, 3)}],
                "overall_ai_probability": round(score, 3),
                "word_count": len(full_text.split()),
            }
        except Exception as e:
            return {"error": str(e)}

    def _analyze_text(self, text: str) -> dict:
        score = self._text_ai_score(text)
        return {
            "pages": [{"page": 1, "text_ai_score": round(score, 3)}],
            "overall_ai_probability": round(score, 3),
            "word_count": len(text.split()),
        }

    def _text_ai_score(self, text: str) -> float:
        """
        Score d'IA pour un texte basé sur des features statistiques.
        Inspiré de : Guo et al. 2023, DetectGPT, GPTZero.
        """
        if len(text) < 50:
            return 0.5  # insufficient data

        words  = text.lower().split()
        n_words = len(words)
        if n_words < 10:
            return 0.5

        # 1. Lexical diversity (Type-Token Ratio)
        ttr = len(set(words)) / n_words
        # High TTR → diverse vocabulary → more likely human
        ttr_score = np.clip(1.0 - ttr * 1.5, 0, 1)

        # 2. Average sentence length
        sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        if sentences:
            avg_len = np.mean([len(s.split()) for s in sentences])
            # AI text: uniform sentence lengths (12–18 words)
            if 12 <= avg_len <= 20:
                len_score = 0.6
            elif avg_len < 8 or avg_len > 30:
                len_score = 0.2
            else:
                len_score = 0.4
        else:
            len_score = 0.5

        # 3. Punctuation density
        punct = sum(1 for c in text if c in ",.;:()[]{}\"'")
        punct_ratio = punct / max(len(text), 1)
        # Very regular punctuation → AI signal
        punct_score = float(np.clip(0.6 - punct_ratio * 5, 0, 1))

        # 4. Paragraph homogeneity
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) > 1:
            para_lens = [len(p.split()) for p in paragraphs]
            cv = float(np.std(para_lens) / (np.mean(para_lens) + 1))
            # Low coefficient of variation → uniform paragraphs → AI
            homo_score = float(np.clip(1.0 - cv, 0, 1))
        else:
            homo_score = 0.5

        score = (
            0.35 * ttr_score +
            0.25 * len_score +
            0.20 * punct_score +
            0.20 * homo_score
        )
        return float(np.clip(score, 0.05, 0.95))
