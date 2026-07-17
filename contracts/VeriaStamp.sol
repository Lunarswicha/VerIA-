// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title VeriaStamp - certification d'images sur Polygon
/// @notice Contrat du memoire VeriaChain (chapitre 10.1.2)
contract VeriaStamp {
    struct Certification {
        address certifier;
        string ipfsHash;
        uint256 timestamp;
        bool revoked;
    }

    mapping(bytes32 => Certification) private certifications;

    event ImageCertified(bytes32 indexed imageHash, address indexed certifier, uint256 ts);
    event CertificationRevoked(bytes32 indexed imageHash, address indexed certifier);

    function certify(bytes32 imageHash, string calldata ipfsHash) external {
        require(certifications[imageHash].timestamp == 0, "Deja certifie");
        certifications[imageHash] = Certification(msg.sender, ipfsHash, block.timestamp, false);
        emit ImageCertified(imageHash, msg.sender, block.timestamp);
    }

    function verify(bytes32 imageHash) external view
        returns (address certifier, string memory ipfsHash, uint256 timestamp, bool revoked) {
        Certification storage c = certifications[imageHash];
        require(c.timestamp > 0, "Non certifie");
        return (c.certifier, c.ipfsHash, c.timestamp, c.revoked);
    }

    function revoke(bytes32 imageHash) external {
        require(certifications[imageHash].certifier == msg.sender, "Non autorise");
        require(!certifications[imageHash].revoked, "Deja revoque");
        certifications[imageHash].revoked = true;
        emit CertificationRevoked(imageHash, msg.sender);
    }
}
