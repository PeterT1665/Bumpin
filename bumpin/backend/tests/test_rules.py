"""Tests for the rules loader module."""

from __future__ import annotations

import os
import pytest

from backend.app.shared.rules import load_rules, load_yaml_rules, load_md_rules


class TestLoadRules:
    def test_load_vendor_eligibility_yaml(self):
        rules = load_rules("vendor_eligibility")
        assert isinstance(rules, dict)
        assert "food" in rules
        assert "required_docs" in rules["food"]
        assert "food_safety" in rules["food"]["required_docs"]

    def test_load_email_policy_md(self):
        policy = load_rules("email_policy")
        assert isinstance(policy, str)
        assert "Tone" in policy
        assert "em dashes" in policy.lower() or "em dash" in policy.lower()

    def test_load_actions_yaml(self):
        rules = load_rules("actions")
        assert isinstance(rules, dict)
        assert "shortage" in rules
        assert "expired_cert" in rules

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_rules("nonexistent_rules_file_xyz")


class TestLoadYamlRules:
    def test_load_vendor_eligibility(self):
        rules = load_yaml_rules("vendor_eligibility")
        assert isinstance(rules, dict)
        assert "beverage" in rules

    def test_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_yaml_rules("no_such_yaml")


class TestLoadMdRules:
    def test_load_email_policy(self):
        text = load_md_rules("email_policy")
        assert "Sign off" in text or "sign off" in text.lower()

    def test_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_md_rules("no_such_md")
