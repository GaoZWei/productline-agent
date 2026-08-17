# 演示规范知识库

本目录保存M4 RAG链路使用的固定演示文档。内容只服务于本仓库的检索、版本过滤和引用测试，不代表真实
遥感行业标准，也不能替代正式业务规范。

## 目录约定

```text
knowledge-base/
├── catalog.json              文档身份、路径、检索元数据和版本状态
├── active/                   默认允许召回的当前有效版本
│   ├── dom/
│   ├── quality/
│   ├── coordinate-system/
│   ├── review/
│   └── delivery/
└── historical/               仅用于显式历史版本查询和失效过滤测试
    ├── coordinate-system/
    └── delivery/
```

当前目录只保存标题化Markdown正文，`catalog.json`是唯一元数据来源。M4.3 Loader会先校验目录条目，
再按扩展名显式选择Markdown或纯文本读取器；不得根据文件名猜测版本、适用范围或有效状态。纯文本契约已
支持`.txt`，但当前16份固定演示规范仍全部使用Markdown。

## 元数据约定

计划要求的字段为`document_type`、`satellite_type`、`product_type`、`processing_level`、
`specification_version`、`effective_date`、`expiry_date`和`permission_scope`。目录额外保存稳定文档ID、
标题、相对路径、生命周期以及历史版本的替代文档ID。

`ACTIVE`文档的`expiry_date`和`replaced_by`必须为`null`；`HISTORICAL`文档必须具有失效日期，并指向
同类型的当前有效替代版本。默认检索只能使用`ACTIVE`文档，历史版本必须由调用方明确请求。
