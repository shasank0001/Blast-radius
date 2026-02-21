# Blast Radius Report — Template (v1)

## Executive summary
- **Intent:** Rename RequestPayload.user_id to RequestPayload.account_id in POST /api/v1/chart/data
- **Anchor(s):** route:POST /api/v1/chart/data, superset/app.py
- **Top risks:**
  - **breaking** in `superset/app.py`:`flask.Flask` — Tool 1 references edge from sym_801a42c7f273d58e
  - **behavior_change** in `superset/app.py`:`__future__.annotations` — Tool 1 imports edge from sym_94c3f16b5acb54dd
  - **behavior_change** in `superset/app.py`:`_typeshed.wsgi.StartResponse` — Tool 1 references edge from sym_8a47f6e30dacc0e6
- **Overall confidence:** High

## Direct structural impacts (AST)
| Impact | Impact risk | Impact surface | Location | Why | Evidence | Confidence |
|---|---|---|---|---|---|---|
| __future__.annotations | behavior_change | api | `superset/app.py`:`__future__.annotations` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports — from __future__ import annotations | H |
| _typeshed.wsgi.StartResponse | behavior_change | data_handling | `superset/app.py`:`_typeshed.wsgi.StartResponse` | Tool 1 references edge from sym_8a47f6e30dacc0e6 | references —         self, environ: WSGIEnvironment, start_response: StartResponse; imports —         from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment | H |
| _typeshed.wsgi.WSGIApplication | behavior_change | api | `superset/app.py`:`_typeshed.wsgi.WSGIApplication` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports —         from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment; references —         wsgi_app: WSGIApplication, | H |
| _typeshed.wsgi.WSGIEnvironment | behavior_change | data_handling | `superset/app.py`:`_typeshed.wsgi.WSGIEnvironment` | Tool 1 references edge from sym_8a47f6e30dacc0e6 | references —         self, environ: WSGIEnvironment, start_response: StartResponse; imports —         from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment | H |
| alembic.config.Config | behavior_change | business_logic | `superset/app.py`:`alembic.config.Config` | Tool 1 calls edge from sym_139ba3afb32943de | calls —             alembic_cfg = Config(); references —             alembic_cfg = Config(); imports — from alembic.config import Config | H |
| alembic.runtime.migration.MigrationContext | behavior_change | data_handling | `superset/app.py`:`alembic.runtime.migration.MigrationContext` | Tool 1 references edge from sym_139ba3afb32943de | references —                 context = MigrationContext.configure(connection); imports — from alembic.runtime.migration import MigrationContext | H |
| alembic.script.ScriptDirectory | behavior_change | data_handling | `superset/app.py`:`alembic.script.ScriptDirectory` | Tool 1 references edge from sym_139ba3afb32943de | references —             script = ScriptDirectory.from_config(alembic_cfg); imports — from alembic.script import ScriptDirectory | H |
| flask.Flask | breaking | data_handling | `superset/app.py`:`flask.Flask` | Tool 1 references edge from sym_801a42c7f273d58e | references — ) -> Flask:; imports — from flask import Flask, Response; inherits — class SupersetApp(Flask):; references — class SupersetApp(Flask): | H |
| flask.Response | behavior_change | business_logic | `superset/app.py`:`flask.Response` | Tool 1 calls edge from sym_2ceeae18f60c8fb3 | calls —                 return Response("", status=204)  # No Content; references —                 return Response("", status=204)  # No Content; references —     def send_static_file(self, filename: str) -> Response:; imports — from flask import Flask, Response | H |
| logging | behavior_change | api | `superset/app.py`:`logging` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports — import logging; references — logger = logging.getLogger(__name__) | H |
| os | behavior_change | data_handling | `superset/app.py`:`os` | Tool 1 references edge from sym_801a42c7f273d58e | references —             str, superset_app_root or os.environ.get("SUPERSET_APP_ROOT", "/"); references —         config_module = superset_config_module or os.environ.get(; imports — import os | H |
| superset.app | behavior_change | data_handling | `superset/app.py`:`superset.app` | Tool 1 references edge from sym_801a42c7f273d58e | references —             app.wsgi_app = AppRootMiddleware(app.wsgi_app, app_root); references —             if app.config["APPLICATION_ROOT"] == "/":; references —                 app.config["APPLICATION_ROOT"] = app_root; references —         app.config.from_object(config_module); references —             app.wsgi_app = AppRootMiddleware(app.wsgi_app, app_root); references —         return app; references —             start_local_extensions_watcher_thread(app); references —         if app.debug:; references —                     theme = app.config[theme_key]; references —                 app.config["STATIC_ASSETS_PREFIX"] = app_root; references —                 app.config["APP_ICON"] = f"{app_root}{app.config['APP_ICON']}"; references —                 app.config["APP_ICON"] = f"{app_root}{app.config['APP_ICON']}"; references —         app_initializer = app.config.get("APP_INITIALIZER", SupersetAppInitializer)(app); references —             if not app.config["STATIC_ASSETS_PREFIX"]:; references —                 app.config.get("APP_ICON", "").startswith("/static/"); references —         app_initializer = app.config.get("APP_INITIALIZER", SupersetAppInitializer)(app); references —     app = SupersetApp(__name__) | H |
| superset.app.AppRootMiddleware | behavior_change | business_logic | `superset/app.py`:`superset.app.AppRootMiddleware` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —             app.wsgi_app = AppRootMiddleware(app.wsgi_app, app_root); references —             app.wsgi_app = AppRootMiddleware(app.wsgi_app, app_root) | H |
| superset.app.SupersetApp | behavior_change | business_logic | `superset/app.py`:`superset.app.SupersetApp` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —     app = SupersetApp(__name__); references —     app = SupersetApp(__name__) | H |
| superset.extensions.db | behavior_change | api | `superset/app.py`:`superset.extensions.db` | Tool 1 imports edge from sym_139ba3afb32943de | imports —             from superset.extensions import db; references —             with db.engine.connect() as connection: | H |
| superset.extensions.local_extensions_watcher.start_local_extensions_watcher_thread | behavior_change | business_logic | `superset/app.py`:`superset.extensions.local_extensions_watcher.start_local_extensions_watcher_thread` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —             start_local_extensions_watcher_thread(app); references —             start_local_extensions_watcher_thread(app); imports — from superset.extensions.local_extensions_watcher import ( | H |
| superset.initialization.SupersetAppInitializer | behavior_change | data_handling | `superset/app.py`:`superset.initialization.SupersetAppInitializer` | Tool 1 references edge from sym_801a42c7f273d58e | references —         app_initializer = app.config.get("APP_INITIALIZER", SupersetAppInitializer)(app); imports — from superset.initialization import SupersetAppInitializer | H |
| superset.tags.core.register_sqla_event_listeners | behavior_change | business_logic | `superset/app.py`:`superset.tags.core.register_sqla_event_listeners` | Tool 1 calls edge from sym_dda47d8b43f7cd2d | calls —                 register_sqla_event_listeners(); imports —                 from superset.tags.core import register_sqla_event_listeners; references —                 register_sqla_event_listeners() | H |
| sys | behavior_change | api | `superset/app.py`:`sys` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports — import sys; references — if sys.version_info >= (3, 11): | H |
| typing.Iterable | behavior_change | data_handling | `superset/app.py`:`typing.Iterable` | Tool 1 references edge from sym_8a47f6e30dacc0e6 | references —     ) -> Iterable[bytes]:; imports — from typing import cast, Iterable, Optional | H |
| typing.Optional | behavior_change | data_handling | `superset/app.py`:`typing.Optional` | Tool 1 references edge from sym_801a42c7f273d58e | references —     superset_app_root: Optional[str] = None,; references —     superset_config_module: Optional[str] = None,; imports — from typing import cast, Iterable, Optional | H |
| typing.TYPE_CHECKING | behavior_change | api | `superset/app.py`:`typing.TYPE_CHECKING` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports —     from typing import TYPE_CHECKING; references —     if TYPE_CHECKING: | H |
| typing.cast | behavior_change | business_logic | `superset/app.py`:`typing.cast` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —         app_root = cast(; references —         app_root = cast(; imports — from typing import cast, Iterable, Optional | H |
| werkzeug.exceptions.NotFound | behavior_change | business_logic | `superset/app.py`:`werkzeug.exceptions.NotFound` | Tool 1 references edge from sym_2ceeae18f60c8fb3 | references —             except NotFound:; calls —             return NotFound()(environ, start_response); references —             return NotFound()(environ, start_response); imports — from werkzeug.exceptions import NotFound | H |
| wsgiref.types.StartResponse | behavior_change | api | `superset/app.py`:`wsgiref.types.StartResponse` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports —     from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment | H |
| wsgiref.types.WSGIApplication | behavior_change | api | `superset/app.py`:`wsgiref.types.WSGIApplication` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports —     from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment | H |
| wsgiref.types.WSGIEnvironment | behavior_change | api | `superset/app.py`:`wsgiref.types.WSGIEnvironment` | Tool 1 imports edge from sym_94c3f16b5acb54dd | imports —     from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment | H |
| alembic.runtime.migration.MigrationContext.configure | behavior_change | business_logic | `superset/app.py`:`alembic.runtime.migration.MigrationContext.configure` | Tool 1 calls edge from sym_139ba3afb32943de | calls —                 context = MigrationContext.configure(connection) | M |
| alembic.script.ScriptDirectory.from_config | behavior_change | business_logic | `superset/app.py`:`alembic.script.ScriptDirectory.from_config` | Tool 1 calls edge from sym_139ba3afb32943de | calls —             script = ScriptDirectory.from_config(alembic_cfg) | M |
| alembic_cfg.set_main_option | behavior_change | business_logic | `superset/app.py`:`alembic_cfg.set_main_option` | Tool 1 calls edge from sym_139ba3afb32943de | calls —             alembic_cfg.set_main_option("script_location", "superset:migrations") | M |
| app.config.from_object | behavior_change | business_logic | `superset/app.py`:`app.config.from_object` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —         app.config.from_object(config_module) | M |
| app.config.get | behavior_change | business_logic | `superset/app.py`:`app.config.get` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —                 app.config.get("APP_ICON", "").startswith("/static/"); calls —         app_initializer = app.config.get("APP_INITIALIZER", SupersetAppInitializer)(app) | M |
| app.config.get('APP_ICON', '').startswith | behavior_change | business_logic | `superset/app.py`:`app.config.get('APP_ICON', '').startswith` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —                 app.config.get("APP_ICON", "").startswith("/static/") | M |
| app.config.get('APP_INITIALIZER', SupersetAppInitializer) | behavior_change | business_logic | `superset/app.py`:`app.config.get('APP_INITIALIZER', SupersetAppInitializer)` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —         app_initializer = app.config.get("APP_INITIALIZER", SupersetAppInitializer)(app) | M |
| app_initializer.init_app | behavior_change | business_logic | `superset/app.py`:`app_initializer.init_app` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —         app_initializer.init_app() | M |
| context.get_current_revision | behavior_change | business_logic | `superset/app.py`:`context.get_current_revision` | Tool 1 calls edge from sym_139ba3afb32943de | calls —                 current_rev = context.get_current_revision() | M |
| environ.get | behavior_change | business_logic | `superset/app.py`:`environ.get` | Tool 1 calls edge from sym_8a47f6e30dacc0e6 | calls —         original_path_info = environ.get("PATH_INFO", "") | M |
| logger.debug | behavior_change | business_logic | `superset/app.py`:`logger.debug` | Tool 1 calls edge from sym_139ba3afb32943de | calls —                 logger.debug(; calls —             logger.debug("Could not check migration status: %s", e); calls —                 logger.debug( | M |
| logger.exception | behavior_change | business_logic | `superset/app.py`:`logger.exception` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —         logger.exception("Failed to create app") | M |
| logging.getLogger | behavior_change | business_logic | `superset/app.py`:`logging.getLogger` | Tool 1 calls edge from sym_94c3f16b5acb54dd | calls — logger = logging.getLogger(__name__) | M |
| original_path_info.removeprefix | behavior_change | business_logic | `superset/app.py`:`original_path_info.removeprefix` | Tool 1 calls edge from sym_8a47f6e30dacc0e6 | calls —             environ["PATH_INFO"] = original_path_info.removeprefix(self.app_root) | M |
| original_path_info.startswith | behavior_change | business_logic | `superset/app.py`:`original_path_info.startswith` | Tool 1 calls edge from sym_8a47f6e30dacc0e6 | calls —         if original_path_info.startswith(self.app_root): | M |
| os.environ.get | behavior_change | business_logic | `superset/app.py`:`os.environ.get` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —             str, superset_app_root or os.environ.get("SUPERSET_APP_ROOT", "/"); calls —         config_module = superset_config_module or os.environ.get( | M |
| script.get_current_head | behavior_change | business_logic | `superset/app.py`:`script.get_current_head` | Tool 1 calls edge from sym_139ba3afb32943de | calls —             head_rev = script.get_current_head() | M |
| self.wsgi_app | behavior_change | business_logic | `superset/app.py`:`self.wsgi_app` | Tool 1 calls edge from sym_8a47f6e30dacc0e6 | calls —             return self.wsgi_app(environ, start_response) | M |
| super().send_static_file | behavior_change | business_logic | `superset/app.py`:`super().send_static_file` | Tool 1 calls edge from sym_2ceeae18f60c8fb3 | calls —                 return super().send_static_file(filename); calls —         return super().send_static_file(filename) | M |
| superset.extensions.db.engine.connect | behavior_change | business_logic | `superset/app.py`:`superset.extensions.db.engine.connect` | Tool 1 calls edge from sym_139ba3afb32943de | calls —             with db.engine.connect() as connection: | M |
| theme.get | behavior_change | business_logic | `superset/app.py`:`theme.get` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —                     token = theme.get("token", {}) | M |
| token.get | behavior_change | business_logic | `superset/app.py`:`token.get` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —                     if token.get("brandLogoUrl", "").startswith("/static/"):; calls —                     if token.get("brandLogoHref") == "/": | M |
| token.get('brandLogoUrl', '').startswith | behavior_change | business_logic | `superset/app.py`:`token.get('brandLogoUrl', '').startswith` | Tool 1 calls edge from sym_801a42c7f273d58e | calls —                     if token.get("brandLogoUrl", "").startswith("/static/"): | M |

## Data-shape impacts (payload lineage)

**Changed field/path:** `RequestPayload.user_id`

### Read sites that will break if removed/renamed

- No read sites identified.

### Transformations

- No transformations identified.

## Unknown risk zones (semantic neighbors)
No unknown risk zones detected.

## Implicit dependencies (temporal coupling)
No temporal coupling detected.

## Tests to run (impact prover)

Ranked list:
1. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_app_root_middleware_path_handling` — imports superset.app
2. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_app_root_middleware_root_path_handling` — imports superset.app
3. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_app_root_middleware_wrong_path_returns_404` — imports superset.app
4. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_redirect_to_login_with_app_root` — imports superset.app
5. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_redirect_to_login_with_custom_target_and_app_root` — imports superset.app
6. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_redirect_to_login_with_query_string_and_app_root` — imports superset.app
7. `tests/integration_tests/test_subdirectory_deployments.py::TestSubdirectoryDeployments::test_redirect_to_login_without_app_root` — imports superset.app
8. `tests/unit_tests/commands/report/execute_test.py::test_get_dashboard_urls_with_exporting_dashboard_only` — imports superset.app
9. `tests/unit_tests/commands/report/execute_test.py::test_get_dashboard_urls_with_multiple_tabs` — imports superset.app
10. `tests/unit_tests/commands/report/execute_test.py::test_get_tab_url` — imports superset.app

## Recommended engineer actions

- **Update schema/docs:** `superset/app.py`:`_typeshed.wsgi.StartResponse` — Review references dependency, `superset/app.py`:`_typeshed.wsgi.WSGIEnvironment` — Review references dependency, `superset/app.py`:`alembic.config.Config` — Review calls dependency, `superset/app.py`:`alembic.runtime.migration.MigrationContext` — Review references dependency, `superset/app.py`:`alembic.script.ScriptDirectory` — Review references dependency, `superset/app.py`:`flask.Flask` — Review references dependency, `superset/app.py`:`flask.Response` — Review calls dependency, `superset/app.py`:`os` — Review references dependency, `superset/app.py`:`superset.app` — Review references dependency, `superset/app.py`:`superset.app.AppRootMiddleware` — Review calls dependency, `superset/app.py`:`superset.app.SupersetApp` — Review calls dependency, `superset/app.py`:`superset.extensions.local_extensions_watcher.start_local_extensions_watcher_thread` — Review calls dependency, `superset/app.py`:`superset.initialization.SupersetAppInitializer` — Review references dependency, `superset/app.py`:`superset.tags.core.register_sqla_event_listeners` — Review calls dependency, `superset/app.py`:`typing.Iterable` — Review references dependency, `superset/app.py`:`typing.Optional` — Review references dependency, `superset/app.py`:`typing.cast` — Review calls dependency, `superset/app.py`:`werkzeug.exceptions.NotFound` — Review references dependency, `superset/app.py`:`alembic.runtime.migration.MigrationContext.configure` — Review calls dependency, `superset/app.py`:`alembic.script.ScriptDirectory.from_config` — Review calls dependency, `superset/app.py`:`alembic_cfg.set_main_option` — Review calls dependency, `superset/app.py`:`app.config.from_object` — Review calls dependency, `superset/app.py`:`app.config.get` — Review calls dependency, `superset/app.py`:`app.config.get('APP_ICON', '').startswith` — Review calls dependency, `superset/app.py`:`app.config.get('APP_INITIALIZER', SupersetAppInitializer)` — Review calls dependency, `superset/app.py`:`app_initializer.init_app` — Review calls dependency, `superset/app.py`:`context.get_current_revision` — Review calls dependency, `superset/app.py`:`environ.get` — Review calls dependency, `superset/app.py`:`logger.debug` — Review calls dependency, `superset/app.py`:`logger.exception` — Review calls dependency, `superset/app.py`:`logging.getLogger` — Review calls dependency, `superset/app.py`:`original_path_info.removeprefix` — Review calls dependency, `superset/app.py`:`original_path_info.startswith` — Review calls dependency, `superset/app.py`:`os.environ.get` — Review calls dependency, `superset/app.py`:`script.get_current_head` — Review calls dependency, `superset/app.py`:`self.wsgi_app` — Review calls dependency, `superset/app.py`:`super().send_static_file` — Review calls dependency, `superset/app.py`:`superset.extensions.db.engine.connect` — Review calls dependency, `superset/app.py`:`theme.get` — Review calls dependency, `superset/app.py`:`token.get` — Review calls dependency, `superset/app.py`:`token.get('brandLogoUrl', '').startswith` — Review calls dependency
- **Update downstream consumers:** `superset/app.py`:`__future__.annotations` — Review imports dependency, `superset/app.py`:`_typeshed.wsgi.WSGIApplication` — Review imports dependency, `superset/app.py`:`logging` — Review imports dependency, `superset/app.py`:`superset.extensions.db` — Review imports dependency, `superset/app.py`:`sys` — Review imports dependency, `superset/app.py`:`typing.TYPE_CHECKING` — Review imports dependency, `superset/app.py`:`wsgiref.types.StartResponse` — Review imports dependency, `superset/app.py`:`wsgiref.types.WSGIApplication` — Review imports dependency, `superset/app.py`:`wsgiref.types.WSGIEnvironment` — Review imports dependency
- **Run tests:** None

## Evidence appendix (machine evidence references)

- AST query id: `25317169d2c8f17f69f4fc2766c882a348aab82efecc613d7a00d62566fa928b`
- Data lineage trace id: `42e0e4c8f524e6c2c6d7062b7f2de3ee439664e3ddfcb6747f70b3c3c610f9df`
- Semantic query id: `beb2d39643afd64ad13f32f39fc5b6faaa9b8c4feea55f370c4515a6d5264f1a`
- Git coupling query id: `ad8ef58f86ec0bb92d0aa0fd82b095c62c4a8c5d49cc34c416e765863a02e822`
- Test impact query id: `f4ecee61da4f5a58459b74912c01433c08adcf6b10942da8a65db366bfab826c`

## Assumptions & limitations

- Semantic-only results are marked as 'unknown risk zones' and require corroboration
- Python-only analysis (v1)
- Static analysis may miss dynamic dispatch patterns
- Cross-file resolution limited to direct imports
