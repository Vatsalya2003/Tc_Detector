"""Tests for the structured-logging rule (GUIDELINES.md, `structured-logging`).

PetClinic has no positive, so the positives here are synthetic, starting with the
guideline's own CorrelationIdFilter example.
"""

from tc_detector.contracts.candidate import Category, Unit
from tc_detector.rules.observability.structured_logging import RULE_ID, detect
from tests.rules.observability.fake_repos import (
    COMMIT,
    JAVA,
    PETCLINIC_LOGBACK,
    RES,
    check,
    shop,
    write,
)

FILTER = """package x;

import org.slf4j.MDC;

class CorrelationIdFilter implements Filter {
  public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain) {
    MDC.put("correlationId", request.getHeader("X-Correlation-Id"));
    try { chain.doFilter(request, response); }
    finally { MDC.remove("correlationId"); }
  }
}
"""


def run(root):
    return check(detect(root, "shop", COMMIT))


def files(root):
    return [(c.service, c.file) for c in run(root)]


# ------------------------------------------------------------------ positives


def test_guideline_correlation_id_filter_is_a_file_candidate(tmp_path):
    shop(tmp_path)
    write(tmp_path, f"shop-orders/{JAVA}/CorrelationIdFilter.java", FILTER)
    [c] = run(tmp_path)
    assert (c.service, c.file, c.unit, c.line_start, c.line_end) == (
        "orders-service",
        f"{JAVA}/CorrelationIdFilter.java",
        Unit.FILE,
        None,
        None,
    )
    assert (c.pattern, c.category, c.rule_id) == (
        "structured-logging",
        Category.OBSERVABILITY,
        RULE_ID,
    )
    assert 'signal: MDC.put of "correlationId" (line 7)' in c.snippet
    assert '7 |     MDC.put("correlationId"' in c.snippet


def test_mdc_constant_key_and_put_closeable_count(tmp_path):
    shop(tmp_path)
    java = (
        "class A {\n  void a() {\n"
        "    MDC.put(Keys.TRACE_ID, id);\n"
        '    MDC.putCloseable("trace-id", id);\n'
        "  }\n}\n"
    )
    write(tmp_path, f"shop-orders/{JAVA}/A.java", java)
    [c] = run(tmp_path)
    assert "MDC.put of Keys.TRACE_ID (line 3)" in c.snippet
    assert 'MDC.put of "trace-id" (line 4)' in c.snippet


def test_logback_pattern_with_trace_id_counts(tmp_path):
    shop(tmp_path)
    xml = (
        '<configuration>\n  <appender name="C" class="ConsoleAppender">\n    <encoder>\n'
        "      <pattern>%d %5p [%X{traceId:-},%X{spanId:-}] %m%n</pattern>\n"
        "    </encoder>\n  </appender>\n</configuration>\n"
    )
    write(tmp_path, f"shop-orders/{RES}/logback-spring.xml", xml)
    [c] = run(tmp_path)
    assert c.file == f"{RES}/logback-spring.xml"
    assert "log pattern with traceId (line 4)" in c.snippet


def test_logback_pattern_property_counts(tmp_path):
    shop(tmp_path)
    xml = (
        '<configuration>\n  <property name="LOG_PATTERN" value="%d [%X{correlationId}] %m%n"/>\n'
        "  <encoder><pattern>${LOG_PATTERN}</pattern></encoder>\n</configuration>\n"
    )
    write(tmp_path, f"shop-orders/{RES}/logback-spring.xml", xml)
    assert files(tmp_path) == [("orders-service", f"{RES}/logback-spring.xml")]


def test_log4j2_pattern_attribute_counts(tmp_path):
    shop(tmp_path)
    xml = '<Configuration>\n  <PatternLayout pattern="%d [%X{trace_id}] %m%n"/>\n</Configuration>\n'
    write(tmp_path, f"shop-payments/{RES}/log4j2-spring.xml", xml)
    assert files(tmp_path) == [("payments", f"{RES}/log4j2-spring.xml")]


def test_logging_pattern_in_application_yml_counts(tmp_path):
    shop(tmp_path)
    yml = (
        "spring:\n  application:\n    name: orders-service\n"
        "logging:\n  pattern:\n    level: '%5p [${spring.application.name:},%X{traceId:-}]'\n"
    )
    write(tmp_path, f"shop-orders/{RES}/application.yml", yml)
    [c] = run(tmp_path)
    assert c.file == f"{RES}/application.yml"
    assert "logging.pattern.level with a trace/correlation ID (line 6)" in c.snippet


def test_logging_pattern_in_properties_counts_with_the_right_line(tmp_path):
    shop(tmp_path)
    props = "# console format\nlogging.pattern.console=%d [%X{correlationId}] %m%n\n"
    write(tmp_path, f"shop-payments/{RES}/application.properties", props)
    [c] = run(tmp_path)
    assert "logging.pattern.console with a trace/correlation ID (line 2)" in c.snippet


# ------------------------------------------------------------------ negatives


def test_plain_log_statements_do_not_count(tmp_path):
    shop(tmp_path)
    java = (
        "class OwnerResource {\n  void a() {\n"
        '    log.info("Saving owner {}", owner);\n'
        '    log.info("traceId " + id);\n'
        "  }\n}\n"
    )
    write(tmp_path, f"shop-orders/{JAVA}/OwnerResource.java", java)
    assert run(tmp_path) == []


def test_petclinic_default_logback_does_not_count(tmp_path):
    shop(tmp_path)
    write(tmp_path, f"shop-orders/{RES}/logback-spring.xml", PETCLINIC_LOGBACK)
    assert run(tmp_path) == []


def test_log_levels_and_id_free_patterns_do_not_count(tmp_path):
    shop(tmp_path)
    yml = (
        "spring:\n  application:\n    name: orders-service\n"
        "logging:\n  level:\n    traceId: DEBUG\n  pattern:\n    console: '%d %m%n'\n"
    )
    write(tmp_path, f"shop-orders/{RES}/application.yml", yml)
    assert run(tmp_path) == []


def test_mdc_put_of_another_key_does_not_count(tmp_path):
    shop(tmp_path)
    write(tmp_path, f"shop-orders/{JAVA}/A.java", 'class A { void a() { MDC.put("userId", u); } }')
    assert run(tmp_path) == []


def test_json_encoder_without_an_id_pattern_does_not_count(tmp_path):
    shop(tmp_path)
    xml = (
        "<configuration>\n"
        '  <encoder class="net.logstash.logback.encoder.LogstashEncoder"/>\n'
        "</configuration>\n"
    )
    write(tmp_path, f"shop-orders/{RES}/logback-spring.xml", xml)
    assert run(tmp_path) == []


def test_commented_out_setup_does_not_count(tmp_path):
    shop(tmp_path)
    xml = "<configuration>\n  <!-- <pattern>%X{traceId} %m</pattern> -->\n</configuration>\n"
    write(tmp_path, f"shop-orders/{RES}/logback-spring.xml", xml)
    write(tmp_path, f"shop-orders/{JAVA}/A.java", 'class A {\n  // MDC.put("traceId", t);\n}\n')
    props = "# logging.pattern.console=%X{traceId} %m\n"
    write(tmp_path, f"shop-payments/{RES}/application.properties", props)
    assert run(tmp_path) == []


def test_test_code_does_not_count(tmp_path):
    shop(tmp_path)
    write(tmp_path, "shop-orders/src/test/java/F.java", FILTER)
    assert run(tmp_path) == []


# ------------------------------------------------------------------ format


def test_snippet_stays_within_the_limit(tmp_path):
    shop(tmp_path)
    java = "class A {\n" + '  void a() { MDC.put("traceId", t); }\n' * 300 + "}\n"
    write(tmp_path, f"shop-orders/{JAVA}/A.java", java)
    [c] = run(tmp_path)
    assert c.snippet.endswith("[... truncated]")
