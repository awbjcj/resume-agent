"""Analytics API schemas: conversion cohorts by source and fit-band."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.base import CamelModel


class CohortOut(CamelModel):
    label: str
    applications: int
    responses: int
    interviews: int
    offers: int
    response_rate: int
    interview_rate: int
    offer_rate: int


class AnalyticsOut(CamelModel):
    by_source: list[CohortOut]
    by_band: list[CohortOut]
