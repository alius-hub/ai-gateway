# 列表筛选接入约定

所有新增的管理台记录列表沿用供应商列表的筛选交互：标题右侧使用
`AppListFilter`，条件通过 `AppFilterDialog` 编辑，支持最多 8 条条件的单层
AND/OR 组合。筛选生效后显示条件标签，可逐条删除或清除全部。

## 前端

1. 在 `frontend/src/utils/listFilterFields.ts` 注册当前列表的可查询字段及类型。
   使用数据库真实字段的 key；关联展示列需要后端提供对应的查询表达式。
   不要把操作列、凭证明文或无法准确查询的展示值放进选项。
2. 列表标题区域引入 `AppListFilter`，传入字段配置、当前 `FilterGroup`，
   处理 `apply` 时将页码重置为 1 并重新请求。切换资源类型时清空旧筛选。
3. 在 `frontend/src/api/` 对应请求中通过 `encodeFilter()` 序列化为 `filters`
   查询参数。已有搜索框、权限范围等参数仍与高级筛选按 AND 叠加。
4. 输入框与按钮沿用 `frontend/src/styles/index.css` 的 `app-control-*` 样式。
5. 弹窗内的完整子列表（如供应商连接、当前成员）也使用同一组件，可通过
   `matchesFilterGroup()` 对完整数据过滤；有分页的候选列表仍交给服务端查询。
6. 主列表的操作区在标题右侧，条件标签独占下一行并与标题左边缘对齐。
   若按钮被右侧容器包裹，在同一工具栏中直接渲染 `AppFilterTags`，
   对 `AppListFilter` 设置 `hide-tags`。两个组件共用相同的字段配置、
   `FilterGroup` 和 `apply` 处理函数，不要把标签留在右侧按钮组内。

## 后端

1. 在列表接口接收 `filters: str | None = Query(None, max_length=4096)`。
2. 将**固定白名单**的 SQLAlchemy 列/关联子查询和字段类型传给
   `app.core.list_filters.filter_expression()`，在计算 `total` 和执行分页
   之前追加到原查询，不替换权限、软删除或作用域条件。
3. 新增筛选字段须同时更新字段配置、白名单和接口测试。可筛的关联数据
   必须在数据库查询阶段处理，不允许仅过滤当前页。
4. 树形列表保留命中项的可见祖先；少量静态配置卡片可以在完整数据集
   加载后用 `matchesFilterGroup()` 筛选。
