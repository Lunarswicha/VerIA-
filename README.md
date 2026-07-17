# VeriaChain — Application locale

Prototype M2 SMI — Système de détection et certification de l'authenticité visuelle.

## Prérequis

- Python 3.10+
- pip

## Installation (une seule fois)

```bash
cd veriachain_app
pip install -r requirements.txt
```

> La première analyse téléchargera automatiquement le modèle HuggingFace (~95 Mo).
> Sans connexion internet, l'application fonctionne en mode analyse fréquentielle (FFT).

## Lancement

```bash
python app.py
```

Ouvrir dans le navigateur : **http://localhost:5000**

Créer un compte lors du premier accès (les données sont en local).

## Configuration (optionnel)

Créer un fichier `.env` à la racine pour activer la blockchain réelle :

```env
POLYGON_RPC=https://polygon-rpc.com
CONTRACT_ADDRESS=0x...          # adresse du contrat VeriaStamp déployé
PRIVATE_KEY=0x...               # clé privée du portefeuille certificateur
IPFS_API_KEY=eyJ...             # clé API Pinata pour le stockage IPFS
DETECTION_MODE=ensemble         # "ensemble" | "huggingface" | "frequency"
```

Sans ces variables, l'application fonctionne en mode démo complet (simulation blockchain locale).

## Déploiement du contrat Solidity

Le contrat `VeriaStamp` (code dans `certification/blockchain.py` → `VERIASTAMP_ABI`) peut être
déployé via [Remix IDE](https://remix.ethereum.org) sur Polygon Mumbai (testnet) ou Polygon Mainnet.

## Architecture

```
veriachain_app/
├── app.py                    # Application Flask principale
├── config.py                 # Configuration
├── detection/
│   └── detector.py           # Pipeline de détection ML + FFT
├── certification/
│   └── blockchain.py         # Interface blockchain Polygon
├── auth/
│   └── users.py              # Modèles utilisateurs (SQLAlchemy)
├── static/
│   ├── css/style.css
│   └── js/app.js
└── templates/                # Pages HTML (Jinja2)
```

## Modes de détection

| Mode        | Description                             | Précision approx. |
|-------------|-----------------------------------------|-------------------|
| `ensemble`  | Modèle HF (65%) + analyse FFT (35%)    | ~82%              |
| `huggingface` | Modèle seul (EfficientNet-B0 fine-tuné) | ~80%              |
| `frequency` | Analyse spectrale + texture locale     | ~68%              |

---
 Prototype académique, Master 2 SMI, Sacha Ferand, 2026*
