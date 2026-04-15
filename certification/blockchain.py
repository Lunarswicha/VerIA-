"""
VeriaChain — Module de certification blockchain VeriaStamp
==========================================================
Gère la certification des images via contrat intelligent Polygon.
Fonctionne en mode "simulation locale" si aucune configuration
blockchain n'est fournie (pour les démos offline).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ABI minimal du contrat VeriaStamp
VERIASTAMP_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "imageHash", "type": "bytes32"},
            {"internalType": "string",  "name": "ipfsHash",  "type": "string"}
        ],
        "name": "certify",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "imageHash", "type": "bytes32"}],
        "name": "verify",
        "outputs": [
            {"internalType": "address", "name": "certifier",  "type": "address"},
            {"internalType": "string",  "name": "ipfsHash",   "type": "string"},
            {"internalType": "uint256", "name": "timestamp",  "type": "uint256"},
            {"internalType": "bool",    "name": "revoked",    "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "imageHash", "type": "bytes32"}],
        "name": "revoke",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


@dataclass
class CertificationRecord:
    cert_id:    str
    image_hash: str
    ipfs_hash:  str
    certifier:  str
    title:      str
    author:     str
    description: str
    timestamp:  str
    tx_hash:    str
    network:    str
    revoked:    bool = False


class VeriaStamp:
    """
    Interface de certification d'images.
    Mode blockchain actif si POLYGON_RPC et CONTRACT_ADDRESS sont configurés.
    Sinon : mode simulation locale (parfait pour démo).
    """

    LOCAL_DB = Path(__file__).parent.parent / "certifications.json"

    def __init__(self, config):
        self.rpc_url          = getattr(config, "POLYGON_RPC", "")
        self.contract_address = getattr(config, "CONTRACT_ADDRESS", "")
        self.private_key      = getattr(config, "PRIVATE_KEY", "")
        self.ipfs_api_key     = getattr(config, "IPFS_API_KEY", "")
        self._w3              = None
        self._contract        = None
        self._simulation_mode = not (self.contract_address and self.private_key)

        if self._simulation_mode:
            logger.info("VeriaStamp : mode simulation locale (pas de clé blockchain configurée).")
        else:
            self._connect_blockchain()

    # ── Blockchain connection ────────────────────────────────────────────────

    def _connect_blockchain(self):
        try:
            from web3 import Web3
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self._w3.is_connected():
                logger.warning("Connexion blockchain échouée, passage en mode simulation.")
                self._simulation_mode = True
                return
            self._contract = self._w3.eth.contract(
                address=Web3.to_checksum_address(self.contract_address),
                abi=VERIASTAMP_ABI,
            )
            logger.info(f"Connecté à Polygon : {self.rpc_url}")
        except Exception as exc:
            logger.warning(f"Erreur web3 : {exc} — mode simulation activé.")
            self._simulation_mode = True

    # ── Public API ───────────────────────────────────────────────────────────

    def certify(
        self,
        image_bytes: bytes,
        title: str,
        author: str,
        description: str = "",
    ) -> CertificationRecord:
        """Certifie une image et retourne le certificat."""
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        cert_id    = f"vc_{image_hash[:16]}"
        timestamp  = datetime.now(timezone.utc).isoformat()

        # Upload metadata to IPFS (or simulate)
        metadata   = {"title": title, "author": author, "description": description,
                      "image_sha256": image_hash, "timestamp": timestamp}
        ipfs_hash  = self._upload_ipfs(metadata)
        tx_hash    = ""
        network    = "simulation"

        if not self._simulation_mode:
            tx_hash, network = self._on_chain_certify(image_hash, ipfs_hash)

        record = CertificationRecord(
            cert_id    = cert_id,
            image_hash = image_hash,
            ipfs_hash  = ipfs_hash,
            certifier  = self._get_address(),
            title      = title,
            author     = author,
            description = description,
            timestamp  = timestamp,
            tx_hash    = tx_hash or self._mock_tx_hash(image_hash),
            network    = network,
        )
        self._save_local(record)
        return record

    def verify_by_hash(self, image_hash: str) -> Optional[CertificationRecord]:
        """Vérifie un certificat par hash SHA-256."""
        # Check local DB first
        record = self._load_local(image_hash)
        if record:
            return record
        # Check on-chain
        if not self._simulation_mode:
            return self._on_chain_verify(image_hash)
        return None

    def verify_by_image(self, image_bytes: bytes) -> Optional[CertificationRecord]:
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        return self.verify_by_hash(image_hash)

    def verify_by_cert_id(self, cert_id: str) -> Optional[CertificationRecord]:
        db = self._load_db()
        for record_dict in db.values():
            if record_dict.get("cert_id") == cert_id:
                return CertificationRecord(**record_dict)
        return None

    # ── On-chain operations ──────────────────────────────────────────────────

    def _on_chain_certify(self, image_hash: str, ipfs_hash: str) -> tuple[str, str]:
        try:
            from web3 import Web3
            hash_bytes = bytes.fromhex(image_hash)
            account    = self._w3.eth.account.from_key(self.private_key)
            tx         = self._contract.functions.certify(hash_bytes, ipfs_hash).build_transaction({
                "from":  account.address,
                "nonce": self._w3.eth.get_transaction_count(account.address),
                "gas":   200000,
            })
            signed = self._w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            return receipt["transactionHash"].hex(), "Polygon Mainnet"
        except Exception as exc:
            logger.error(f"Erreur certification on-chain : {exc}")
            return "", "error"

    def _on_chain_verify(self, image_hash: str) -> Optional[CertificationRecord]:
        try:
            hash_bytes = bytes.fromhex(image_hash)
            result     = self._contract.functions.verify(hash_bytes).call()
            if result[2] == 0:   # timestamp == 0 → not certified
                return None
            return CertificationRecord(
                cert_id    = f"vc_{image_hash[:16]}",
                image_hash = image_hash,
                ipfs_hash  = result[1],
                certifier  = result[0],
                title      = "(depuis blockchain)",
                author     = result[0],
                description = "",
                timestamp  = datetime.fromtimestamp(result[2], tz=timezone.utc).isoformat(),
                tx_hash    = "",
                network    = "Polygon Mainnet",
                revoked    = result[3],
            )
        except Exception as exc:
            logger.warning(f"Erreur vérification on-chain : {exc}")
            return None

    # ── IPFS ─────────────────────────────────────────────────────────────────

    def _upload_ipfs(self, metadata: dict) -> str:
        if not self.ipfs_api_key:
            # Return a deterministic mock IPFS hash
            content = json.dumps(metadata, sort_keys=True).encode()
            return "Qm" + hashlib.sha256(content).hexdigest()[:44]
        try:
            import requests
            resp = requests.post(
                "https://api.pinata.cloud/pinning/pinJSONToIPFS",
                headers={"Authorization": f"Bearer {self.ipfs_api_key}"},
                json={"pinataContent": metadata},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()["IpfsHash"]
        except Exception as exc:
            logger.warning(f"IPFS upload échoué : {exc}")
            content = json.dumps(metadata, sort_keys=True).encode()
            return "Qm" + hashlib.sha256(content).hexdigest()[:44]

    # ── Local DB (JSON) ───────────────────────────────────────────────────────

    def _load_db(self) -> dict:
        if not self.LOCAL_DB.exists():
            return {}
        try:
            return json.loads(self.LOCAL_DB.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_local(self, record: CertificationRecord):
        db = self._load_db()
        db[record.image_hash] = record.__dict__
        self.LOCAL_DB.write_text(json.dumps(db, indent=2), encoding="utf-8")

    def _load_local(self, image_hash: str) -> Optional[CertificationRecord]:
        db = self._load_db()
        if image_hash in db:
            return CertificationRecord(**db[image_hash])
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_address(self) -> str:
        if self.private_key:
            try:
                from web3 import Web3
                return Web3().eth.account.from_key(self.private_key).address
            except Exception:
                pass
        return "0x" + "0" * 40

    @staticmethod
    def _mock_tx_hash(image_hash: str) -> str:
        return "0x" + hashlib.sha256((image_hash + str(time.time())).encode()).hexdigest()
