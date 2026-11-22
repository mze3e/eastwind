"""Synthetic private wealth records used by the offline workflows."""
from __future__ import annotations

CLIENT = {"id": "CL-1001", "version": "1", "name": "Mei Tan", "email": "mei.tan@clients.eastwind.example",
          "risk_profile": "moderate", "investment_horizon_years": 5,
          "tax_identifier": "SYNTHETIC-TAX-001", "owner": "Relationship Management"}
MANDATE = {"id": "MANDATE-1", "version": "1", "client_id": CLIENT["id"], "risk_ceiling": "moderate",
           "permitted_purposes": ["ELIGIBILITY_CHECK"], "approver": "risk.officer@eastwind.example"}
ACCOUNT = {"id": "SG-PB-1001842", "version": "1", "client_id": CLIENT["id"], "currency": "SGD",
           "holdings": [{"product_id": "INS-MMF", "amount": 100000}]}
PRODUCTS = {"INS-MMF": {"id": "INS-MMF", "version": "1", "name": "SGD money market", "risk": "low"},
            "INS-HK-NOTE": {"id": "INS-HK-NOTE", "version": "1", "name": "Structured note", "risk": "high"}}
SOURCE = {"id": "eastwind-house-view", "version": "1", "owner": "Chief Investment Office",
          "classification": "C1", "lineage": "Investment committee minutes",
          "effective": "2025-01-01T00:00:00+00:00", "expiry": "2030-01-01T00:00:00+00:00",
          "purposes": ["ELIGIBILITY_CHECK"], "text": "Maintain a diversified cash allocation."}

SOURCES = {
    "client_profile": {"owner": "Relationship Management", "classification": "C2",
                       "lineage": "Client onboarding", "version": "1",
                       "effective": "2026-01-01", "purposes": ["ELIGIBILITY_CHECK"]},
    "account_holdings": {"owner": "Investment Operations", "classification": "C2",
                         "lineage": "Account ledger", "version": "1",
                         "effective": "2026-01-01", "purposes": ["ELIGIBILITY_CHECK"]},
    "product_profile": {"owner": "Product Governance", "classification": "C1",
                        "lineage": "Approved product register", "version": "1",
                        "effective": "2026-01-01", "purposes": ["ELIGIBILITY_CHECK"]},
    "house_view": {key: SOURCE[key] for key in ("owner", "classification", "lineage",
                                                  "version", "effective", "expiry", "purposes")},
}

# Roles are host-assigned. The model cannot request a broader role.
ROLE_FIELDS = {
    "relationship_manager": {"name": "visible", "email": "visible", "risk_profile": "visible",
                             "investment_horizon_years": "visible", "tax_identifier": "masked"},
    "agent": {"name": "visible", "email": "masked", "risk_profile": "visible",
              "investment_horizon_years": "visible", "tax_identifier": "denied"},
    "visitor": {"name": "denied", "email": "denied", "risk_profile": "denied",
                "investment_horizon_years": "denied", "tax_identifier": "denied"},
}
