"""SRC-001: source.agent_type must be a published value for the envelope kind."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conformance_test import FLEET_AGENT_TYPES, LEAD_AGENT_TYPES, check_source


def _src001(env):
    [r] = [r for r in check_source(env) if r.test_id == "SRC-001"]
    return r


def test_the_published_enums():
    assert LEAD_AGENT_TYPES == {"sales_chat", "sales_voice", "inbound_voice", "service_text", "service_voice"}
    assert FLEET_AGENT_TYPES == {"vehicle_agent", "fleet_ops_agent"}


@pytest.mark.parametrize("agent_type", sorted(LEAD_AGENT_TYPES))
def test_a_lead_envelope_with_a_published_lead_value_passes(agent_type):
    r = _src001({"lead": {}, "source": {"agent_type": agent_type}})
    assert r.status == "PASS" and r.required


@pytest.mark.parametrize("agent_type", sorted(FLEET_AGENT_TYPES))
def test_a_fleet_envelope_with_a_published_fleet_value_passes(agent_type):
    assert _src001({"fleet": {}, "source": {"agent_type": agent_type}}).status == "PASS"


@pytest.mark.parametrize("agent_type", ["dealer_agent", "bdc_chat", "head_hunter", "", "vehicle_agent"])
def test_anything_else_on_a_lead_envelope_fails(agent_type):
    # vehicle_agent included: a fleet value on a lead envelope is not conformant.
    assert _src001({"lead": {}, "source": {"agent_type": agent_type}}).status == "FAIL"


@pytest.mark.parametrize("agent_type", ["dealer_agent", "sales_chat", ""])
def test_anything_else_on_a_fleet_envelope_fails(agent_type):
    assert _src001({"fleet": {}, "source": {"agent_type": agent_type}}).status == "FAIL"


def test_a_missing_source_fails():
    assert _src001({"lead": {}}).status == "FAIL"
