"""Indicadores determinísticos do histórico persistido, sem chamadas de IA."""

from config import Settings
from database import repository
from services.analysis_service import get_analysis


def get_dashboard_data(settings: Settings) -> dict:
    """Agrega riscos após revalidar evidências, mantendo contagens sem multiplicar joins."""
    counts = repository.get_dashboard_counts(settings.database_path, settings.demo_mode)
    headers = repository.list_analyses(settings.database_path, settings.demo_mode)
    risk_items = []
    recent_analyses = []
    limited_analysis_count = 0
    for header in headers:
        analysis = get_analysis(settings, header["id"])
        if analysis is None:
            continue
        risks = [finding for finding in analysis.findings if finding.category in {"risk", "inconsistency"}]
        risk_items.extend({"finding": finding, "analysis_id": analysis.id, "created_at": analysis.created_at} for finding in risks)
        if any(not warning.startswith("ANÁLISE SIMULADA") for warning in analysis.warnings):
            limited_analysis_count += 1
        if len(recent_analyses) < 5:
            recent_analyses.append({
                "id": analysis.id, "created_at": analysis.created_at, "model": analysis.model,
                "finding_count": len(analysis.findings), "risk_count": len(risks),
                "high_priority_count": sum(finding.severity == "high" for finding in risks),
            })

    priority = {"high": 0, "medium": 1, "low": 2}
    risk_items.sort(key=lambda item: (
        priority[item["finding"].severity], -item["created_at"].timestamp(), item["finding"].id,
    ))
    by_priority = {severity: 0 for severity in priority}
    by_category = {"risk": 0, "inconsistency": 0}
    for item in risk_items:
        finding = item["finding"]
        by_priority[finding.severity] += 1
        by_category[finding.category] += 1
    return {
        **counts,
        "risk_count": len(risk_items),
        "high_priority_count": by_priority["high"],
        "risks_by_priority": by_priority,
        "risks_by_category": by_category,
        "high_priority_alerts": [item for item in risk_items if item["finding"].severity == "high"][:5],
        "recommendations": risk_items[:5],
        "recent_analyses": recent_analyses,
        "limited_analysis_count": limited_analysis_count,
    }
