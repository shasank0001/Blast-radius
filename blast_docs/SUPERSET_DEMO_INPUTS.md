# Superset Demo Inputs for Blast Radius MCP

These are realistic, copy-paste-ready inputs for running the Blast Radius workflow against Apache Superset.

## Shared repo root

Use this for all scenarios in this workspace:

```text
/home/shasank/shasank/Hackathons/ai_for_vizag/superset
```

All file anchors below are repo-relative to that `repo_root`.

---

## Scenario 1 — Rename dashboard payload field (`dashboard_title` → `title`)

```yaml
intent: "Rename request.dashboard_title to request.title in POST /api/v1/dashboard/"
repo_root: "/home/shasank/shasank/Hackathons/ai_for_vizag/superset"
anchors:
  - "superset/dashboards/schemas.py"
  - "superset/dashboards/api.py"
  - "route:POST /api/v1/dashboard/"
  - "symbol:DashboardPostSchema"
  - "symbol:DashboardRestApi.post"
diff: |
  diff --git a/superset/dashboards/schemas.py b/superset/dashboards/schemas.py
  index 4f8b123..a29bcde 100644
  --- a/superset/dashboards/schemas.py
  +++ b/superset/dashboards/schemas.py
  @@ -346,7 +346,7 @@ class DashboardPostSchema(BaseDashboardSchema):
  -    dashboard_title = fields.String(
  +    title = fields.String(
         metadata={"description": dashboard_title_description},
         allow_none=True,
         validate=Length(0, 500),
```

---

## Scenario 2 — Tighten slug validation on dashboard create

```yaml
intent: "Tighten request.slug validation in POST /api/v1/dashboard/ from min length 1 to 3"
repo_root: "/home/shasank/shasank/Hackathons/ai_for_vizag/superset"
anchors:
  - "superset/dashboards/schemas.py"
  - "route:POST /api/v1/dashboard/"
  - "symbol:DashboardPostSchema"
  - "symbol:DashboardPostSchema.slug"
diff: |
  diff --git a/superset/dashboards/schemas.py b/superset/dashboards/schemas.py
  index 4f8b123..f65e88a 100644
  --- a/superset/dashboards/schemas.py
  +++ b/superset/dashboards/schemas.py
  @@ -352,7 +352,7 @@ class DashboardPostSchema(BaseDashboardSchema):
       slug = fields.String(
           metadata={"description": slug_description},
           allow_none=True,
  -        validate=[Length(1, 255)],
  +        validate=[Length(3, 255)],
       )
```

---

## Scenario 3 — Rename chart list response field (`slice_name` → `chart_title`)

```yaml
intent: "Rename response.slice_name to response.chart_title in GET /api/v1/chart/ list response"
repo_root: "/home/shasank/shasank/Hackathons/ai_for_vizag/superset"
anchors:
  - "superset/charts/api.py"
  - "route:GET /api/v1/chart/"
  - "symbol:ChartRestApi"
  - "symbol:ChartRestApi.list_columns"
diff: |
  diff --git a/superset/charts/api.py b/superset/charts/api.py
  index 1b2c333..9a4de11 100644
  --- a/superset/charts/api.py
  +++ b/superset/charts/api.py
  @@ -171,7 +171,7 @@ class ChartRestApi(BaseSupersetModelRestApi):
           "params",
  -        "slice_name",
  +        "chart_title",
           "slice_url",
           "table.default_endpoint",
           "table.table_name",
```

---

## Scenario 4 — Tighten dataset update schema nullability

```yaml
intent: "Tighten request.schema from nullable to required in PUT /api/v1/dataset/"
repo_root: "/home/shasank/shasank/Hackathons/ai_for_vizag/superset"
anchors:
  - "superset/datasets/schemas.py"
  - "superset/datasets/api.py"
  - "route:PUT /api/v1/dataset/"
  - "symbol:DatasetPutSchema"
  - "symbol:DatasetPutSchema.schema"
diff: |
  diff --git a/superset/datasets/schemas.py b/superset/datasets/schemas.py
  index e5b1001..8c2a449 100644
  --- a/superset/datasets/schemas.py
  +++ b/superset/datasets/schemas.py
  @@ -185,7 +185,7 @@ class DatasetPutSchema(Schema):
       fetch_values_predicate = fields.String(allow_none=True, validate=Length(0, 1000))
       catalog = fields.String(allow_none=True, validate=Length(0, 250))
  -    schema = fields.String(allow_none=True, validate=Length(0, 255))
  +    schema = fields.String(allow_none=False, validate=Length(1, 255))
       description = fields.String(allow_none=True)
       main_dttm_col = fields.String(allow_none=True)
       currency_code_column = fields.String(allow_none=True, validate=Length(0, 250))
```

---

## Scenario 5 — Structural refactor in dashboard DAO method name

```yaml
intent: "Refactor DashboardDAO method name get_tabs_for_dashboard to get_dashboard_tabs and update callers"
repo_root: "/home/shasank/shasank/Hackathons/ai_for_vizag/superset"
anchors:
  - "superset/daos/dashboard.py"
  - "superset/dashboards/api.py"
  - "symbol:DashboardDAO.get_tabs_for_dashboard"
  - "symbol:DashboardRestApi.get_tabs"
diff: |
  diff --git a/superset/daos/dashboard.py b/superset/daos/dashboard.py
  index c412998..78a2ff1 100644
  --- a/superset/daos/dashboard.py
  +++ b/superset/daos/dashboard.py
  @@ -97,7 +97,7 @@ class DashboardDAO(BaseDAO[Dashboard]):
       @staticmethod
  -    def get_tabs_for_dashboard(id_or_slug: str) -> dict[str, Any]:
  +    def get_dashboard_tabs(id_or_slug: str) -> dict[str, Any]:
           dashboard = DashboardDAO.get_by_id_or_slug(id_or_slug)
           return dashboard.tabs

  diff --git a/superset/dashboards/api.py b/superset/dashboards/api.py
  index d1a0ee2..65fd810 100644
  --- a/superset/dashboards/api.py
  +++ b/superset/dashboards/api.py
  @@ -613,7 +613,7 @@ class DashboardRestApi(CustomTagsOptimizationMixin, BaseSupersetModelRestApi):
       try:
  -        tabs = DashboardDAO.get_tabs_for_dashboard(id_or_slug)
  +        tabs = DashboardDAO.get_dashboard_tabs(id_or_slug)
           native_filters = DashboardDAO.get_native_filter_configuration(id_or_slug)
```

---

## Suggested demo run order

1. Scenario 1 (field rename, rich API blast radius)
2. Scenario 2 (validation tightening)
3. Scenario 4 (schema nullability change)
4. Scenario 3 (response contract change)
5. Scenario 5 (structural refactor)

This order shows increasing breadth: payload lineage → validation impact → contract changes → structural dependencies.
