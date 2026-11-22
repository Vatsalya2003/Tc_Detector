"""Builds tiny fake repos on disk for the scanner tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

COMMIT = "a" * 40
PARENT_POM = "<project><modules><module>shop-orders</module></modules></project>"
POM = "<project><artifactId>x</artifactId></project>"
JAVA_DIR = "src/main/java/com/shop"


def write(root: Path, rel: str, text: str = "") -> Path:
    """Create the file `root/rel` (and its folders) holding `text`."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def app_yml(name: str) -> str:
    return f"spring:\n  application:\n    name: {name}\n"


def shop_repo(root: Path) -> Path:
    """Parent pom + 2 services + docker-compose, with files the scan must skip.

    shop-orders sets spring.application.name; shop-payments doesn't, so it is named
    after its folder minus the shared "shop-" prefix.
    """
    write(root, "pom.xml", PARENT_POM)
    write(root, "docker-compose.yml", "services: {}\n")
    write(root, "README.md", "# shop\n")
    write(root, "target/junk.jar")  # build output: skipped
    write(root, "node_modules/x/index.js")  # skipped

    o = "shop-orders/"
    write(root, o + "pom.xml", POM)
    write(root, o + "src/main/resources/application.yml", app_yml("orders-service"))
    write(root, o + "src/main/resources/logback-spring.xml", "<configuration/>")
    write(root, o + "src/main/resources/openapi.yaml", "openapi: 3.0.3\n")
    write(root, o + "src/main/resources/db/schema.sql", "create table t;")  # no group
    write(root, o + JAVA_DIR + "/OrderController.java", "class OrderController {}")
    write(root, o + "src/main/proto/order.proto", 'syntax = "proto3";')
    write(root, o + "src/test/java/com/shop/OrderTest.java", "class OrderTest {}")  # skipped
    write(root, o + "target/classes/Order.class")  # skipped

    p = "shop-payments/"
    write(root, p + "pom.xml", POM)
    write(root, p + "src/main/resources/application.properties", "server.port=8081\n")
    write(root, p + "src/main/resources/log4j2.xml", "<Configuration/>")
    write(root, p + "src/main/resources/events.asyncapi.yaml", "asyncapi: 2.6.0\n")
    write(root, p + "src/main/avro/payment.avsc", '{"type": "record"}')
    write(root, p + JAVA_DIR + "/PaymentClient.java", "class PaymentClient {}")
    return root


def fingerprint(root: Path) -> dict[str, tuple[int, str]]:
    """Every path under `root` with its mtime and content hash, to prove nothing changed."""
    return {
        p.relative_to(root).as_posix(): (
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir",
        )
        for p in sorted(root.rglob("*"))
    }
