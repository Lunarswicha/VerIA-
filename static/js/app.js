/**
 * VeriaChain — JavaScript principal
 */

// Charger le statut du système au démarrage
document.addEventListener("DOMContentLoaded", () => {
  fetch("/api/status")
    .then(r => r.json())
    .then(data => {
      const badge = document.getElementById("mode-badge");
      if (!badge) return;
      const modeLabels = {
        ensemble:    "Mode ensemble (ML + FFT)",
        huggingface: "Mode modèle HuggingFace",
        frequency:   "Mode analyse fréquentielle",
      };
      badge.textContent = modeLabels[data.detection_mode] || data.detection_mode;
    })
    .catch(() => {
      const badge = document.getElementById("mode-badge");
      if (badge) badge.textContent = "En ligne";
    });
});

// ── Drag & drop générique ─────────────────────────────────────────────────────

function initUploadZone(zoneId, inputId, onFile) {
  const zone  = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("active"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("active"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("active");
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  });
  input.addEventListener("change", () => {
    if (input.files[0]) onFile(input.files[0]);
  });
}

// ── Formatage ─────────────────────────────────────────────────────────────────

function fmtPct(v) { return (v * 100).toFixed(1) + "%"; }
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + " o";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " Ko";
  return (bytes / 1048576).toFixed(1) + " Mo";
}
function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("fr-FR") + " " + d.toLocaleTimeString("fr-FR", {hour:"2-digit",minute:"2-digit"});
}

// ── Preview ───────────────────────────────────────────────────────────────────

function showPreview(file, imgId, nameId, sizeId) {
  const nameEl = document.getElementById(nameId);
  const sizeEl = document.getElementById(sizeId);
  if (nameEl) nameEl.textContent = file.name;
  if (sizeEl) sizeEl.textContent = fmtSize(file.size);

  if (imgId && file.type.startsWith("image/")) {
    const imgEl = document.getElementById(imgId);
    if (!imgEl) return;
    const reader = new FileReader();
    reader.onload = e => { imgEl.src = e.target.result; imgEl.parentElement.style.display = "block"; };
    reader.readAsDataURL(file);
  }
}

// ── Progress steps ────────────────────────────────────────────────────────────

class StepProgress {
  constructor(steps) {
    this.steps = steps; // array of {dotId, textId, label}
    this.current = 0;
    this._reset();
  }
  _reset() { this.steps.forEach((s, i) => this._setState(i, "pending")); }
  _setState(i, state) {
    const dot = document.getElementById(this.steps[i].dotId);
    if (!dot) return;
    dot.className = "step-dot " + state;
    dot.innerHTML = state === "done" ? '<i class="bi bi-check"></i>' : (i + 1);
  }
  async runAll(durations) {
    for (let i = 0; i < this.steps.length; i++) {
      this._setState(i, "running");
      await delay(durations[i] || 600);
      this._setState(i, "done");
    }
  }
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── API call helper ───────────────────────────────────────────────────────────

async function postForm(url, formData) {
  const resp = await fetch(url, { method: "POST", body: formData });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || "Erreur serveur");
  return data;
}

// ── Detect page ───────────────────────────────────────────────────────────────

const detectPage = {
  file: null,

  init() {
    initUploadZone("detect-zone", "detect-input", f => this.onFile(f));
  },

  onFile(file) {
    this.file = file;
    showPreview(file, "detect-preview-img", "detect-fname", "detect-fsize");
    const wrap = document.getElementById("detect-preview-wrap");
    if (wrap) wrap.style.display = "flex";
    const btn = document.getElementById("detect-btn");
    if (btn) btn.disabled = false;
    // Reset result
    const res = document.getElementById("detect-result");
    if (res) res.style.display = "none";
  },

  async run() {
    if (!this.file) return;
    const btn = document.getElementById("detect-btn");
    if (btn) btn.disabled = true;

    // Show progress
    const prog = document.getElementById("detect-progress");
    if (prog) prog.style.display = "block";
    const res = document.getElementById("detect-result");
    if (res) res.style.display = "none";

    // Animate steps (while real analysis runs in background)
    const stepsAnimation = new StepProgress([
      { dotId: "step-d0" }, { dotId: "step-d1" }, { dotId: "step-d2" },
      { dotId: "step-d3" }, { dotId: "step-d4" },
    ]);

    const fd = new FormData();
    fd.append("file", this.file);

    // Run analysis and animation in parallel
    const [data] = await Promise.all([
      postForm("/api/detect", fd).catch(err => ({ error: err.message })),
      stepsAnimation.runAll([500, 700, 600, 700, 400]),
    ]);

    if (prog) prog.style.display = "none";
    if (btn) btn.disabled = false;

    if (data.error) {
      alert("Erreur : " + data.error);
      return;
    }

    this.showResult(data);
  },

  showResult(data) {
    const res = document.getElementById("detect-result");
    if (!res) return;
    res.style.display = "block";

    const score = data.ai_probability;
    const pct   = Math.round(score * 100);

    // Verdict
    let cls, icon, label;
    if (score < 0.20)      { cls = "authentic";  icon = "bi-shield-check";   }
    else if (score < 0.40) { cls = "authentic";  icon = "bi-shield-check";   }
    else if (score < 0.60) { cls = "uncertain";  icon = "bi-question-circle"; }
    else if (score < 0.75) { cls = "ai-gen";     icon = "bi-exclamation-triangle"; }
    else                   { cls = "ai-strong";  icon = "bi-x-circle";       }

    const verdictEl = document.getElementById("verdict-card");
    if (verdictEl) {
      verdictEl.className = "verdict " + cls;
      verdictEl.innerHTML = `
        <i class="verdict-icon bi ${icon}"></i>
        <div>
          <h3>${data.label}</h3>
          <p>Probabilité IA : <strong>${pct}%</strong> — Confiance : ${Math.round(data.confidence * 100)}%</p>
          ${data.model_score !== null && data.model_score !== undefined
            ? `<p style="font-size:0.75rem;margin-top:4px">Modèle HF : ${Math.round(data.model_score*100)}% / Analyse FFT : ${Math.round(data.freq_score*100)}%</p>`
            : `<p style="font-size:0.75rem;margin-top:4px">Score FFT : ${Math.round(data.freq_score*100)}%</p>`
          }
        </div>`;
    }

    // Gauge
    const needle = document.getElementById("gauge-needle");
    if (needle) needle.style.left = pct + "%";
    const scoreEl = document.getElementById("gauge-value");
    if (scoreEl) scoreEl.textContent = pct;

    // SHA-256
    const hashEl = document.getElementById("result-hash");
    if (hashEl) hashEl.textContent = data.sha256;

    // Metrics
    if (data.metrics) {
      const m = data.metrics;
      this._metric("m-fft",  m.fft_energy_ratio);
      this._metric("m-edge", 1 - m.edge_sharpness);
      this._metric("m-ent",  m.color_entropy);
      this._metric("m-var",  m.local_variance);
      this._metric("m-noise",m.noise_level);
      this._metric("m-prnu", m.prnu_score);
    }
  },

  _metric(id, value) {
    const val = document.getElementById(id + "-val");
    const bar = document.getElementById(id + "-bar");
    if (val) val.textContent = Math.round(value * 100) + "%";
    if (bar) bar.style.width = Math.round(value * 100) + "%";
  },
};

// ── Certify page ──────────────────────────────────────────────────────────────

const certifyPage = {
  file: null,

  init() {
    initUploadZone("cert-zone", "cert-input", f => this.onFile(f));
  },

  onFile(file) {
    this.file = file;
    showPreview(file, "cert-preview-img", "cert-fname", "cert-fsize");
    const wrap = document.getElementById("cert-preview-wrap");
    if (wrap) wrap.style.display = "flex";
    const form = document.getElementById("cert-meta-form");
    if (form) form.style.display = "block";
    const btn = document.getElementById("cert-btn");
    if (btn) btn.disabled = false;
    const res = document.getElementById("cert-result");
    if (res) res.style.display = "none";
  },

  async run() {
    if (!this.file) return;
    const title  = document.getElementById("cert-title")?.value.trim();
    const author = document.getElementById("cert-author")?.value.trim();
    if (!title)  { alert("Le titre est obligatoire."); return; }
    if (!author) { alert("Le nom de l'auteur est obligatoire."); return; }

    const btn = document.getElementById("cert-btn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Certification…'; }

    const fd = new FormData();
    fd.append("file", this.file);
    fd.append("title", title);
    fd.append("author", author);
    fd.append("description", document.getElementById("cert-desc")?.value.trim() || "");

    try {
      const data = await postForm("/api/certify", fd);
      this.showCert(data);
    } catch(err) {
      alert("Erreur : " + err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-patch-check"></i> Générer le certificat'; }
    }
  },

  showCert(data) {
    const res = document.getElementById("cert-result");
    if (!res) return;
    res.style.display = "block";
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set("cert-id-val",     data.cert_id);
    set("cert-hash-val",   data.image_hash);
    set("cert-ipfs-val",   data.ipfs_hash);
    set("cert-author-val", data.author);
    set("cert-title-val",  data.title);
    set("cert-ts-val",     fmtDate(data.timestamp));
    set("cert-tx-val",     data.tx_hash);
    set("cert-net-val",    data.network);
  },
};

// ── Verify page ───────────────────────────────────────────────────────────────

const verifyPage = {
  file: null,

  init() {
    initUploadZone("ver-zone", "ver-input", f => {
      this.file = f;
      showPreview(f, null, "ver-fname", "ver-fsize");
      document.getElementById("ver-preview-wrap").style.display = "block";
    });
  },

  async run() {
    const btn = document.getElementById("ver-btn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Vérification…'; }

    const fd = new FormData();
    if (this.file) fd.append("file", this.file);
    const certId = document.getElementById("ver-cert-id")?.value.trim();
    if (certId) fd.append("cert_id", certId);

    try {
      const data = await postForm("/api/verify", fd);
      this.showResult(data);
    } catch(err) {
      alert("Erreur : " + err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-search"></i> Vérifier'; }
    }
  },

  showResult(data) {
    const res = document.getElementById("ver-result");
    if (!res) return;
    res.style.display = "block";
    if (!data.found) {
      res.innerHTML = `<div class="verdict uncertain"><i class="bi bi-question-circle verdict-icon"></i><div><h3>Aucun certificat trouvé</h3><p>${data.message}</p></div></div>`;
      return;
    }
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    res.innerHTML = `
      <div class="cert-card">
        <div class="cert-header"><i class="bi bi-patch-check-fill text-success fs-4"></i><h3>Certificat valide${data.revoked ? " — RÉVOQUÉ" : ""}</h3></div>
        <div class="cert-field"><div class="lbl">Identifiant</div><div class="val hash" id="v-cert-id"></div></div>
        <div class="cert-field"><div class="lbl">Hash SHA-256</div><div class="val hash" id="v-hash"></div></div>
        <div class="cert-field"><div class="lbl">Titre</div><div class="val" id="v-title"></div></div>
        <div class="cert-field"><div class="lbl">Auteur</div><div class="val" id="v-author"></div></div>
        <div class="cert-field"><div class="lbl">Certifié le</div><div class="val" id="v-ts"></div></div>
        <div class="cert-field"><div class="lbl">Transaction</div><div class="val hash" id="v-tx"></div></div>
        <div class="cert-field"><div class="lbl">Réseau</div><div class="val" id="v-net"></div></div>
      </div>`;
    set("v-cert-id", data.cert_id);
    set("v-hash",    data.image_hash);
    set("v-title",   data.title);
    set("v-author",  data.author);
    set("v-ts",      fmtDate(data.timestamp));
    set("v-tx",      data.tx_hash);
    set("v-net",     data.network);
  },
};
