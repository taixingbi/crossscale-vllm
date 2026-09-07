"""Supply a private administrator CIDR and redact it from review artifacts."""
import ipaddress
import json
import os
from pathlib import Path
import sys


def admin_cidr():
    value = os.environ.get("EKS_ADMIN_CIDR") or "203.0.113.10/32"
    network = ipaddress.ip_network(value, strict=True)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError("Review workflow requires one administrator IPv4 /32")
    return str(network)


def redact(text, cidr):
    return text.replace(cidr, "REDACTED_ADMIN_CIDR").replace(cidr.split("/")[0], "REDACTED_ADMIN_IP")


def main():
    cidr = admin_cidr()
    root = Path(os.environ["RUNNER_TEMP"])
    if sys.argv[1] == "prepare":
        # Mask both forms before any Terraform output; never echo unvalidated input.
        print("::add-mask::" + cidr)
        print("::add-mask::" + cidr.split("/")[0])
        path = root / "admin.tfvars.json"
        path.touch(mode=0o600)
        path.write_text(json.dumps({"admin_cidrs": [cidr]}))
    elif sys.argv[1] == "redact":
        for path in (root / "review").glob("cluster-plan.*"):
            path.write_text(redact(path.read_text(), cidr))
    else:
        raise ValueError("Expected prepare or redact")


if __name__ == "__main__":
    main()
