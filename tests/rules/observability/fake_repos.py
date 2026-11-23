"""Tiny fake repos for the observability rule tests."""

from __future__ import annotations

from pathlib import Path

from tc_detector.contracts.candidate import Candidate
from tests.scanner.fake_repo import COMMIT, PARENT_POM, app_yml, write

__all__ = ["COMMIT", "JAVA", "dep", "PETCLINIC_LOGBACK", "RES", "check", "pom", "shop", "write"]

JAVA = "src/main/java/com/shop"
RES = "src/main/resources"

# customers-service's logback-spring.xml in PetClinic, word for word (GUIDELINES negative).
PETCLINIC_LOGBACK = """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <include resource="org/springframework/boot/logging/logback/base.xml"/>
    <!-- Required for Loglevel managment into the Spring Petclinic Admin Server-->
    <jmxConfigurator/>
</configuration>
"""


def pom(dependencies: str = "", extra: str = "") -> str:
    """A service pom.xml; `dependencies` goes inside <dependencies>."""
    return (
        "<project>\n"
        "  <artifactId>svc</artifactId>\n"
        f"{extra}"
        "  <dependencies>\n"
        f"{dependencies}"
        "  </dependencies>\n"
        "</project>\n"
    )


def dep(artifact: str, group: str = "io.example") -> str:
    return (
        "    <dependency>\n"
        f"      <groupId>{group}</groupId>\n"
        f"      <artifactId>{artifact}</artifactId>\n"
        "    </dependency>\n"
    )


def shop(root: Path, orders_pom: str = "", payments_pom: str = "") -> Path:
    """Parent pom + services orders-service (shop-orders) and payments (shop-payments)."""
    write(root, "pom.xml", PARENT_POM)
    write(root, "shop-orders/pom.xml", orders_pom or pom())
    write(root, f"shop-orders/{RES}/application.yml", app_yml("orders-service"))
    write(root, "shop-payments/pom.xml", payments_pom or pom())
    return root


def check(candidates: list[Candidate]) -> list[Candidate]:
    """Every candidate passes the frozen format's checks again after a JSON round trip."""
    for c in candidates:
        assert Candidate.from_json(c.to_json()) == c
        assert c.commit == COMMIT
        assert len(c.snippet) <= 2000
    return candidates
