"""immutable-data-contracts rule, on small fake repos built in tmp_path (offline, no targets/)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.contracts.immutable_data_contracts import PATTERN, RULE_ID, detect, main

COMMIT = "0" * 40
SVC = "shop-orders"  # service folder; named orders-service by its application.yml
JAVA = f"{SVC}/src/main/java/shop"


def write(repo: Path, files: dict[str, str]) -> Path:
    """Create a fake repo with one service plus `files` ({relative path: content})."""
    base = {
        f"{SVC}/pom.xml": "<project/>\n",
        f"{SVC}/src/main/resources/application.yml": (
            "spring:\n  application:\n    name: orders-service\n"
        ),
    }
    for rel, content in {**base, **files}.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return repo


def run(repo: Path) -> dict[str, Candidate]:
    """Candidates keyed by file name, e.g. "OrderDetails.java"."""
    return {Path(c.file).name: c for c in detect(repo, "demo", COMMIT)}


# ------------------------------------------------------------- what counts


def test_record_dto_is_a_file_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{JAVA}/dto/OrderDetails.java": """\
                package shop.dto;

                public record OrderDetails(int id, String note) {
                }
            """
        },
    )
    [c] = detect(repo, "demo", COMMIT)
    assert c.file == "src/main/java/shop/dto/OrderDetails.java"  # relative to service root
    assert c.service == "orders-service"  # from spring.application.name
    assert (c.unit, c.line_start, c.line_end) == (Unit.FILE, None, None)
    assert (c.pattern, c.category, c.rule_id) == (PATTERN, Category.API_STABILITY, RULE_ID)
    assert c.id == f"demo:orders-service:{c.file}:file:immutable-data-contracts"
    assert "type OrderDetails (line 3): record" in c.snippet
    assert "folder 'dto'" in c.snippet
    assert "public record OrderDetails(int id, String note) {" in c.snippet


def test_lombok_value_used_by_a_controller_is_a_candidate(tmp_path):
    # No wire folder or name here: the wire sign is the controller that returns it.
    repo = write(
        tmp_path,
        {
            f"{JAVA}/domain/OrderLine.java": """\
                package shop.domain;

                import lombok.Value;

                @Value
                public class OrderLine {
                    String sku;
                    int quantity;
                }
            """,
            f"{JAVA}/web/OrderController.java": """\
                package shop.web;

                @RestController
                class OrderController {
                    @GetMapping("/lines/{id}")
                    OrderLine line(@PathVariable int id) { return null; }
                }
            """,
        },
    )
    c = run(repo)["OrderLine.java"]
    assert "Lombok @Value" in c.snippet
    assert "used by OrderController.java" in c.snippet


def test_ignore_unknown_class_is_a_candidate_even_with_setters(tmp_path):
    # GUIDELINES counts ignoreUnknown on its own; the setters only become a note.
    repo = write(
        tmp_path,
        {
            f"{JAVA}/billing/PaymentResult.java": """\
                package shop.billing;

                import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

                @JsonIgnoreProperties(ignoreUnknown = true)
                public class PaymentResult {
                    private String status;
                    public void setStatus(String status) { this.status = status; }
                }
            """
        },
    )
    c = run(repo)["PaymentResult.java"]
    assert "@JsonIgnoreProperties(ignoreUnknown = true)" in c.snippet
    assert "Jackson annotation" in c.snippet
    assert "note: mutable: has setter(s) setStatus" in c.snippet


def test_two_dtos_in_one_controller_make_one_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{JAVA}/web/OrderResource.java": """\
                package shop.web;

                @RestController
                class OrderResource {
                    @GetMapping("/orders")
                    Orders read() { return null; }

                    record Orders(List<Order> items) {
                    }

                    record OrderSummary(int count) {
                    }
                }
            """
        },
    )
    [c] = detect(repo, "demo", COMMIT)
    assert c.file == "src/main/java/shop/web/OrderResource.java"
    assert "type Orders (line 8): record" in c.snippet
    assert "note: only shallowly immutable: items is a List" in c.snippet
    assert "type OrderSummary (line 11): record" in c.snippet


# ------------------------------------------------------- what doesn't count


def test_entity_with_setters_is_not_a_candidate(tmp_path):
    # Like customers-service Owner.java. ignoreUnknown is added so the entity has a
    # contract signal and a wire sign: only the @Entity exclusion keeps it out.
    repo = write(
        tmp_path,
        {
            f"{JAVA}/dto/Owner.java": """\
                package shop.dto;

                @Entity
                @Table(name = "owners")
                @JsonIgnoreProperties(ignoreUnknown = true)
                public class Owner {
                    @Id
                    private Integer id;
                    private String firstName;
                    public void setFirstName(String firstName) { this.firstName = firstName; }
                }
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_test_code_is_skipped(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{SVC}/src/test/java/shop/dto/FakeOrderDetails.java": """\
                package shop.dto;

                public record FakeOrderDetails(int id) {
                }
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_record_used_only_inside_the_service_is_not_a_candidate(tmp_path):
    # No Jackson, no wire folder or name, and no HTTP/messaging file uses it.
    repo = write(
        tmp_path,
        {
            f"{JAVA}/pricing/Discount.java": """\
                package shop.pricing;

                record Discount(int percent) {
                }
            """,
            f"{JAVA}/pricing/PriceCalculator.java": """\
                package shop.pricing;

                class PriceCalculator {
                    int apply(int price, Discount d) { return price * (100 - d.percent()) / 100; }
                }
            """,
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_configuration_properties_record_and_its_nested_records_are_not_candidates(tmp_path):
    # A config record. The nested name ends in "Details" (a wire sign),
    # so only the exclusion of everything inside the config record keeps it out.
    repo = write(
        tmp_path,
        {
            f"{JAVA}/system/ShopProperties.java": """\
                package shop.system;

                @ConfigurationProperties(prefix = "shop")
                public record ShopProperties(CacheDetails cache) {
                    public record CacheDetails(int ttl, int heapSize) {
                    }
                }
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_spring_value_on_a_field_is_not_lombok_value(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{JAVA}/dto/OrderSettings.java": """\
                package shop.dto;

                import org.springframework.beans.factory.annotation.Value;

                @Component
                public class OrderSettings {
                    @Value("${shop.max-items}")
                    private int maxItems;
                }
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_record_in_a_comment_or_string_is_not_a_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{JAVA}/dto/Notes.java": """\
                package shop.dto;

                // public record OrderDetails(int id) {}
                class Notes {
                    String text = "public record OrderDetails(int id) {}";
                }
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


# ------------------------------------------------------------ output format


def test_service_name_falls_back_to_folder_minus_shared_prefix(tmp_path):
    files = {
        "shop-billing/pom.xml": "<project/>\n",
        "shop-orders/pom.xml": "<project/>\n",
        "shop-orders/src/main/java/shop/dto/OrderDetails.java": "record OrderDetails(int id) {}\n",
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content, encoding="utf-8")
    [c] = detect(tmp_path, "demo", COMMIT)
    assert c.service == "orders"


def test_repo_name_defaults_to_folder_name(tmp_path):
    repo = write(
        tmp_path / "spring-petclinic-microservices",
        {f"{JAVA}/dto/OrderDetails.java": "public record OrderDetails(int id) {}\n"},
    )
    [c] = detect(repo, commit=COMMIT)
    assert c.repo == "spring-petclinic-microservices"


def test_snippet_stays_within_the_limit(tmp_path):
    fields = ",\n".join(f"    String field{i:03d}" for i in range(300))
    repo = write(
        tmp_path,
        {f"{JAVA}/dto/HugeDetails.java": f"public record HugeDetails(\n{fields}) {{\n}}\n"},
    )
    [c] = detect(repo, "demo", COMMIT)
    assert len(c.snippet) <= SNIPPET_MAX_CHARS
    assert c.snippet.endswith("[... truncated]")


def test_main_prints_json_lines(tmp_path, capsys):
    repo = write(
        tmp_path,
        {
            f"{JAVA}/dto/OrderDetails.java": "public record OrderDetails(int id) {}\n",
            f"{JAVA}/dto/OrderRequest.java": "public record OrderRequest(String note) {}\n",
        },
    )
    assert main([str(repo), "--repo-name", "demo", "--commit", COMMIT]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    for line in lines:  # one candidate per line, as the scoring script reads them
        c = Candidate.from_json(line)
        assert c.to_dict() == json.loads(line)
        assert c.unit == Unit.FILE
