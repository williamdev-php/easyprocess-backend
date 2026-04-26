"""Smoke tests: verify AutoBlogger modules import without errors and key
objects are accessible.  No database or network needed."""
from __future__ import annotations


# ── Module imports ──────────────────────────────────────────────────────────


def test_import_models():
    from app.autoblogger import models

    assert hasattr(models, "BlogPostAB")
    assert hasattr(models, "Source")
    assert hasattr(models, "CreditBalance")
    assert hasattr(models, "CreditTransaction")
    assert hasattr(models, "ContentSchedule")
    assert hasattr(models, "UserSettings")
    assert hasattr(models, "AutoBloggerSubscription")
    assert hasattr(models, "AutoBloggerPayment")
    assert hasattr(models, "Notification")


def test_import_api():
    from app.autoblogger import api

    assert hasattr(api, "router")


def test_import_billing():
    from app.autoblogger import billing

    assert hasattr(billing, "router")


def test_import_generator():
    from app.autoblogger import generator


def test_import_publisher():
    from app.autoblogger import publisher


def test_import_credits():
    from app.autoblogger import credits


def test_import_scheduler():
    from app.autoblogger import scheduler


def test_import_sanitize():
    from app.autoblogger import sanitize


def test_import_exceptions():
    from app.autoblogger import exceptions


def test_import_images():
    from app.autoblogger import images


def test_import_notifications():
    from app.autoblogger import notifications


def test_import_email_service():
    from app.autoblogger import email_service


def test_import_email_templates():
    from app.autoblogger import email_templates


def test_import_router():
    from app.autoblogger import router

    assert hasattr(router, "router")


# ── Integration routers ────────────────────────────────────────────────────


def test_import_shopify_integration():
    from app.autoblogger.integrations import shopify, shopify_router

    assert hasattr(shopify_router, "router")


def test_import_wordpress_integration():
    from app.autoblogger.integrations import wordpress, wordpress_router

    assert hasattr(wordpress_router, "router")


def test_import_qvicko_integration():
    from app.autoblogger.integrations import qvicko, qvicko_router

    assert hasattr(qvicko_router, "router")


# ── Enums ───────────────────────────────────────────────────────────────────


def test_enum_platform_type():
    from app.autoblogger.models import PlatformType

    assert PlatformType.SHOPIFY == "SHOPIFY"
    assert PlatformType.QVICKO == "QVICKO"
    assert PlatformType.CUSTOM == "CUSTOM"


def test_enum_post_status():
    from app.autoblogger.models import PostStatus

    assert PostStatus.DRAFT == "DRAFT"
    assert PostStatus.GENERATING == "GENERATING"
    assert PostStatus.REVIEW == "REVIEW"
    assert PostStatus.PUBLISHED == "PUBLISHED"
    assert PostStatus.FAILED == "FAILED"


def test_enum_task_frequency():
    from app.autoblogger.models import TaskFrequency

    assert TaskFrequency.DAILY == "DAILY"
    assert TaskFrequency.WEEKLY == "WEEKLY"


# ── Pydantic schemas ───────────────────────────────────────────────────────


def test_pydantic_source_create():
    from app.autoblogger.api import SourceCreate

    assert SourceCreate.model_fields
    assert "name" in SourceCreate.model_fields
    assert "platform" in SourceCreate.model_fields


def test_pydantic_post_create():
    from app.autoblogger.api import PostCreate

    assert PostCreate.model_fields
    assert "title" in PostCreate.model_fields


def test_pydantic_post_update():
    from app.autoblogger.api import PostUpdate

    assert PostUpdate.model_fields


def test_pydantic_schedule_create():
    from app.autoblogger.api import ScheduleCreate

    assert ScheduleCreate.model_fields


def test_pydantic_settings_update():
    from app.autoblogger.api import SettingsUpdate

    assert SettingsUpdate.model_fields


# ── Router routes ───────────────────────────────────────────────────────────


def test_api_router_has_routes():
    from app.autoblogger.api import router

    route_paths = [r.path for r in router.routes]
    assert any("/sources" in p for p in route_paths)
    assert any("/posts" in p for p in route_paths)
    assert any("/schedules" in p for p in route_paths)
    assert any("/settings" in p for p in route_paths)
    assert any("/credits" in p for p in route_paths)


def test_billing_router_has_routes():
    from app.autoblogger.billing import router

    route_paths = [r.path for r in router.routes]
    assert len(route_paths) > 0


def test_shopify_router_has_routes():
    from app.autoblogger.integrations.shopify_router import router

    route_paths = [r.path for r in router.routes]
    assert len(route_paths) > 0


def test_wordpress_router_has_routes():
    from app.autoblogger.integrations.wordpress_router import router

    route_paths = [r.path for r in router.routes]
    assert len(route_paths) > 0


def test_qvicko_router_has_routes():
    from app.autoblogger.integrations.qvicko_router import router

    route_paths = [r.path for r in router.routes]
    assert len(route_paths) > 0
