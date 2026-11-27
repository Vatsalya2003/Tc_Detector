"""Feature-flags rule, on small fake repos built in tmp_path (offline, no targets/).

PetClinic has no feature flags, so every positive here is synthetic, starting with the
guideline's own @ConditionalOnProperty example. tests/fixtures/feature_flags_repo is the
labelled synthetic repo the rule is scored on (see its README).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.contracts.label import load_labels
from tc_detector.rules.abstraction.feature_flags import (
    FRAMEWORK_PREFIXES,
    PATTERN,
    RULE_ID,
    conditional_keys,
    detect,
    is_framework_key,
    strip_comments,
)

COMMIT = "0" * 40
JAVA = "src/main/java/x"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "feature_flags_repo"


def write(repo: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return repo


def pom(*artifacts: str) -> str:
    deps = "".join(f"<dependency><artifactId>{a}</artifactId></dependency>\n" for a in artifacts)
    return f"<project>\n<dependencies>\n{deps}</dependencies>\n</project>\n"


def run(tmp_path: Path, java: str, *artifacts: str) -> list[tuple[int, int, str]]:
    """(line_start, line_end, snippet) of every candidate for one Java file in one service."""
    files = {
        "svc/pom.xml": pom(*(artifacts or ("spring-boot-starter-web",))),
        "svc/src/main/resources/application.properties": "spring.application.name=svc\n",
        f"svc/{JAVA}/Flags.java": java,
        "other/pom.xml": pom("spring-boot-starter-web"),
    }
    cands = detect(write(tmp_path, files), "demo", COMMIT)
    return [(c.line_start, c.line_end, c.snippet) for c in cands]


def lines(found: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    return [(a, b) for a, b, _ in found]


# ------------------------------------------------- signal A: @ConditionalOnProperty

GUIDELINE_EXAMPLE = """\
class Config {
    @Bean
    @ConditionalOnProperty(name = "petclinic.features.vet-ratings", havingValue = "true")
    VetRatingService vetRatingService() { return null; }
}
"""


def test_guideline_conditional_on_property_example(tmp_path):
    found = run(tmp_path, GUIDELINE_EXAMPLE)
    assert lines(found) == [(3, 3)]
    assert "@ConditionalOnProperty on petclinic.features.vet-ratings" in found[0][2]
    assert "code: @ConditionalOnProperty(name = " in found[0][2]


@pytest.mark.parametrize(
    "annotation",
    [
        '@ConditionalOnProperty("ratings.enabled")',
        '@ConditionalOnProperty(value = "ratings.enabled")',
        '@ConditionalOnProperty({"ratings.a", "ratings.b"})',
        '@ConditionalOnProperty(prefix = "ratings", name = "enabled", matchIfMissing = true)',
        '@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(name = "app.x")',
        "@ConditionalOnProperty(name = Flags.RATINGS)",  # key not a literal: still app code
    ],
)
def test_conditional_on_property_app_keys(tmp_path, annotation):
    assert lines(run(tmp_path, f"class C {{\n    {annotation}\n    void m() {{}}\n}}\n")) == [
        (2, 2)
    ]


def test_multi_line_conditional_covers_the_whole_annotation(tmp_path):
    java = 'class C {\n  @ConditionalOnProperty(\n      prefix = "ratings.beta",\n'
    java += '      name = "enabled")\n  void m() {}\n}\n'
    found = run(tmp_path, java)
    assert lines(found) == [(2, 4)]
    assert "on ratings.beta.enabled" in found[0][2]


@pytest.mark.parametrize(
    "annotation",
    [
        '@ConditionalOnProperty(name = "spring.cache.enabled")',
        '@ConditionalOnProperty(prefix = "management.metrics", name = "enabled")',
        '@ConditionalOnProperty("eureka.client.enabled")',
        '@ConditionalOnProperty({"server.ssl.enabled", "logging.x"})',
        '@ConditionalOnProperty(prefix = "spring.ai.chat.client", name = "enabled")',
    ],
)
def test_conditional_on_framework_keys_is_not_a_flag(tmp_path, annotation):
    assert run(tmp_path, f"class C {{\n    {annotation}\n    void m() {{}}\n}}\n") == []


def test_mixed_app_and_framework_keys_still_fires(tmp_path):
    java = 'class C {\n  @ConditionalOnProperty({"spring.x", "app.feature"})\n  void m() {}\n}\n'
    assert lines(run(tmp_path, java)) == [(2, 2)]


def test_profile_is_not_a_flag(tmp_path):
    """Guideline negative: vets-service CacheConfig @Profile("production")."""
    java = 'class C {\n  @Bean\n  @Profile("production")\n  Cache cache() { return null; }\n}\n'
    assert run(tmp_path, java) == []


def test_commented_out_annotation_is_ignored(tmp_path):
    java = 'class C {\n  // @ConditionalOnProperty("app.x")\n  /* @ConditionalOnProperty("app.y")\n'
    java += "  */\n  void m() {}\n}\n"
    assert run(tmp_path, java) == []


def test_annotation_in_a_string_is_ignored(tmp_path):
    java = 'class C {\n  String s = "use @ConditionalOnProperty here";\n'
    java += '  String t = "@Value(\\"${app.x}\\") boolean x; if (x) {}";\n}\n'
    assert run(tmp_path, java) == []


def test_conditional_in_test_code_is_ignored(tmp_path):
    files = {
        "svc/pom.xml": pom("spring-boot-starter-web"),
        "svc/src/test/java/x/T.java": GUIDELINE_EXAMPLE,
        "other/pom.xml": pom("spring-boot-starter-web"),
    }
    assert detect(write(tmp_path, files), "demo", COMMIT) == []


def test_yaml_property_line_is_never_a_candidate(tmp_path):
    """Guideline: don't label the property line; spring.ai...enabled is a framework switch."""
    files = {
        "svc/pom.xml": pom("spring-boot-starter-web"),
        "svc/src/main/resources/application.yml": (
            "spring:\n  application:\n    name: svc\n  profiles:\n    active: prod\n"
            "  ai:\n    chat:\n      client:\n        enabled: true\n"
            "petclinic:\n  features:\n    vet-ratings: true\n"
        ),
        "other/pom.xml": pom("spring-boot-starter-web"),
    }
    assert detect(write(tmp_path, files), "demo", COMMIT) == []


# ------------------------------------------------------ signal B: @Value boolean


def value_class(field: str, condition: str) -> str:
    return f"class C {{\n    {field}\n    void m() {{\n        if ({condition}) {{\n"
    "            run();\n        }\n    }\n}\n"


@pytest.mark.parametrize(
    ("field", "condition"),
    [
        ('@Value("${ratings.show-stars:false}") private boolean showStars;', "showStars"),
        ('@Value("${ratings.show-stars}") private Boolean showStars;', "!showStars"),
        ('@Value("${app.beta}") private final boolean beta = false;', "this.beta && ready"),
        ('@Value("${app.beta}")\n    @Nullable\n    private boolean beta;', "beta"),
    ],
)
def test_if_on_value_boolean(tmp_path, field, condition):
    found = run(tmp_path, value_class(field, condition))
    assert len(found) == 1
    assert "if on @Value boolean" in found[0][2]
    assert found[0][2].count("code: if (") == 1


def test_value_boolean_range_is_the_if_line(tmp_path):
    java = 'class C {\n  @Value("${app.x}") boolean x;\n  void m() {\n    if (x\n'
    java += "        && y) {\n    }\n  }\n}\n"
    assert lines(run(tmp_path, java)) == [(4, 5)]


@pytest.mark.parametrize(
    ("field", "condition"),
    [
        # Guideline edge case: a timeout is config, not a flag.
        ('@Value("${ratings.timeout-ms:500}") private int timeoutMs;', "timeoutMs > 1000"),
        ('@Value("${ratings.url}") private String url;', "url != null"),
        # Guideline edge case: spring.profiles.active is not a flag.
        ('@Value("${spring.profiles.active}") private String p;', '"prod".equals(p)'),
        # Framework key, same filter as signal A.
        ('@Value("${spring.cloud.discovery.enabled:true}") private boolean d;', "d"),
        ('@Value("${management.x.enabled}") private boolean m;', "m"),
    ],
)
def test_if_on_non_flag_value_is_not_a_flag(tmp_path, field, condition):
    assert run(tmp_path, value_class(field, condition)) == []


def test_value_boolean_not_tested_by_an_if_is_not_a_candidate(tmp_path):
    java = 'class C {\n  @Value("${app.x}") boolean x;\n  boolean get() { return x; }\n}\n'
    assert run(tmp_path, java) == []


def test_if_on_another_name_containing_the_field_is_not_matched(tmp_path):
    java = value_class('@Value("${app.x}") private boolean beta;', "betaTester")
    assert run(tmp_path, java) == []


# ---------------------------------------------------- signal C: flag-library calls


def if_class(condition: str) -> str:
    return f"class C {{\n    void m() {{\n        if ({condition}) {{\n        }}\n    }}\n}}\n"


@pytest.mark.parametrize(
    ("condition", "call"),
    [
        ('ldClient.boolVariation("discounts", context, false)', "LaunchDarkly boolVariation"),
        ('ff4j.check("bulk-import")', "FF4J check"),
        ('getFf4j().check("x")', "FF4J check"),
        ("CatalogFeatures.NEW_SEARCH.isActive()", "Togglz Feature.isActive()"),
        ("NEW_SEARCH.isActive()", "Togglz Feature.isActive()"),
        ('client.getBooleanValue("fast-search", false)', "OpenFeature getBooleanValue"),
    ],
)
def test_library_specific_calls_fire_without_a_dependency(tmp_path, condition, call):
    found = run(tmp_path, if_class(condition))
    assert lines(found) == [(3, 3)]
    assert f"if on flag library call {call}" in found[0][2]
    assert "supporting" not in found[0][2]


@pytest.mark.parametrize(
    ("condition", "artifact"),
    [
        ('unleash.isEnabled("new-layout")', "unleash-client-java"),
        ('flags.isFeatureEnabled("x")', "flagsmith-java-client"),
        ("featureManager.isActive(MyFeatures.X)", "togglz-core"),
        ('features.check("x")', "ff4j-core"),
    ],
)
def test_generic_calls_fire_with_a_flag_library_dependency(tmp_path, condition, artifact):
    found = run(tmp_path, if_class(condition), artifact)
    assert lines(found) == [(3, 3)]
    assert "supporting:" in found[0][2]


@pytest.mark.parametrize(
    "condition",
    [
        'unleash.isEnabled("new-layout")',
        'validator.isEnabled("strict")',
        "account.isEnabled()",
        'flags.isFeatureEnabled("x")',
        "featureManager.isActive(MyFeatures.X)",
        'features.check("x")',
        "transaction.isActive()",
    ],
)
def test_generic_or_unrelated_calls_without_a_dependency_do_not_fire(tmp_path, condition):
    assert run(tmp_path, if_class(condition)) == []


def test_generic_call_needs_the_right_library(tmp_path):
    """`x.check(` needs FF4J, `x.isActive(arg)` needs Togglz; another flag library isn't enough."""
    assert run(tmp_path / "a", if_class('features.check("x")'), "unleash-client-java") == []
    assert run(tmp_path / "b", if_class("m.isActive(F.X)"), "launchdarkly-java-server-sdk") == []


def test_no_arg_is_enabled_is_not_a_flag_even_with_a_dependency(tmp_path):
    assert run(tmp_path, if_class("account.isEnabled()"), "unleash-client-java") == []


def test_library_call_outside_an_if_is_not_a_check(tmp_path):
    java = 'class C {\n  boolean m() {\n    return ld.boolVariation("x", c, false);\n  }\n}\n'
    assert run(tmp_path, java) == []


def test_dependency_alone_is_never_a_candidate(tmp_path):
    """Signal D is supporting evidence only: the unit is the check."""
    assert run(tmp_path, "class C {}\n", "unleash-client-java", "togglz-core") == []


def test_dependencies_are_listed_in_the_snippet(tmp_path):
    found = run(
        tmp_path,
        if_class('unleash.isEnabled("x")'),
        "unleash-client-java",
        "launchdarkly-java-server-sdk",
    )
    snippet = found[0][2]
    assert "supporting: LaunchDarkly dependency at pom.xml:4" in snippet
    assert "supporting: Unleash dependency at pom.xml:3" in snippet


def test_value_boolean_and_library_call_in_one_if_is_one_candidate(tmp_path):
    java = 'class C {\n  @Value("${app.x}") boolean x;\n  void m() {\n'
    java += '    if (x && ldClient.boolVariation("y", c, false)) {}\n  }\n}\n'
    found = run(tmp_path, java)
    assert lines(found) == [(4, 4)]
    assert "@Value boolean x" in found[0][2] and "boolVariation" in found[0][2]


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("spring.cache.enabled", True),
        ("spring", True),
        ("management.metrics.enabled", True),
        ("debug", True),
        ("springfield.feature", False),
        ("petclinic.features.vet-ratings", False),
        ("app.server.enabled", False),
    ],
)
def test_is_framework_key(key, expected):
    assert is_framework_key(key) is expected


def test_framework_prefixes_include_the_agreed_ones():
    assert {"spring", "management", "server", "eureka", "logging"} <= set(FRAMEWORK_PREFIXES)


@pytest.mark.parametrize(
    ("args", "keys"),
    [
        ('name = "a.b", havingValue = "true"', ["a.b"]),
        ('prefix = "a", name = "b"', ["a.b"]),
        ('prefix = "a.", name = {"b", "c"}', ["a.b", "a.c"]),
        ('prefix = "a"', ["a"]),
        ('"a.b"', ["a.b"]),
        ('"a.b", havingValue = "x"', ["a.b"]),
        ('{"a", "b"}, havingValue = "x"', ["a", "b"]),
        ("name = Keys.X", []),
        ("", []),
    ],
)
def test_conditional_keys(args, keys):
    assert conditional_keys(args) == keys


def test_strip_comments_keeps_strings_and_line_numbers():
    text = 'a // x\nb = "http://h/*no*/";\n/* y\nz */ c\n'
    out = strip_comments(text)
    assert out.count("\n") == text.count("\n") and len(out) == len(text)
    assert '"http://h/*no*/"' in out
    assert "x" not in out.split("\n")[0] and "y" not in out and "z" not in out
    assert out.split("\n")[3].strip() == "c"


# ------------------------------------------------------- shape and fixture


def test_candidates_pass_the_candidate_checks(tmp_path):
    files = {
        "svc/pom.xml": pom("x"),
        f"svc/{JAVA}/C.java": GUIDELINE_EXAMPLE,
        "other/pom.xml": pom("x"),
    }
    (c,) = detect(write(tmp_path, files), "demo", COMMIT)
    assert Candidate.from_json(c.to_json()) == c
    assert (c.unit, c.pattern, c.category, c.rule_id) == (
        Unit.LINE_RANGE,
        PATTERN,
        Category.CONFIGURABILITY,
        RULE_ID,
    )
    assert (c.file, c.line_start, c.line_end) == (f"{JAVA}/C.java", 3, 3)
    assert c.id == f"demo:svc:{JAVA}/C.java:3-3:feature-flags"


def test_pattern_and_rule_id_strings():
    assert PATTERN == "feature-flags"
    assert RULE_ID == "configurability-feature-flags-01"


def test_snippet_stays_within_the_limit(tmp_path):
    cond = " && ".join(f'ld.boolVariation("flag-{i}", c, false)' for i in range(200))
    (found,) = run(tmp_path, if_class(cond))
    assert len(found[2]) <= SNIPPET_MAX_CHARS


def test_fixture_candidates_match_its_labels_exactly():
    """The synthetic fixture: every positive found, no negative fires."""
    labels = load_labels(FIXTURE / "labels.json")
    cands = detect(FIXTURE, "feature-flags-fixture", COMMIT)
    expected = {(lbl.service, lbl.file, lbl.line_start, lbl.line_end) for lbl in labels}
    assert {(c.service, c.file, c.line_start, c.line_end) for c in cands} == expected
    assert all(lbl.is_tc for lbl in labels)
