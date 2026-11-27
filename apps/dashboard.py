# ruff: noqa: E402
import os
import sys
from functools import partial
from pathlib import Path

# Streamlit 直接执行入口文件，服务源码仍按 monorepo 模块加载。
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(path)
    for path in (
        root,
        root / "broker-gateway/src",
        root / "trade-planner/src",
        root / "investment-journal/src",
        root / "personal-cio-agent/src",
    )
    if str(path) not in sys.path
]

import streamlit as st
from dotenv import dotenv_values
from duckdb import Error as DuckDBError
from yaml import YAMLError

from apps import dashboard_views as views
from shared.db.database import DEFAULT_CONFIG_DIR, DEFAULT_DB_PATH, ROOT


def main() -> None:
    st.set_page_config(
        page_title="个人 CIO", page_icon=":material/space_dashboard:", layout="wide"
    )
    if (
        st.get_option("server.address") not in ("127.0.0.1", "::1")
        or not st.get_option("server.enableXsrfProtection")
        or not st.get_option("server.enableCORS")
    ):
        st.error("仅允许环回地址访问，且须保持跨站请求保护开启。")
        st.stop()
    local = os.environ.get("DATABASE_PATH") or dotenv_values(ROOT / ".env").get(
        "DATABASE_PATH"
    )
    data = views.DashboardData(
        ROOT / local if local else DEFAULT_DB_PATH, DEFAULT_CONFIG_DIR
    )
    st.html("""
        <style>
        .stMainBlockContainer {max-width: 85rem; padding-top: 2.25rem; padding-bottom: 3rem;}
        [data-testid="stSidebar"] h2 {font-size: 1.3rem; padding-bottom: 0;}
        [data-testid="stMain"] h1 {font-size: 2.15rem;}
        [data-testid="stMetricValue"] {font-size: 1.65rem;}
        </style>
    """)
    st.sidebar.header("个人 CIO")
    st.sidebar.caption("投资审阅工作台")
    pages = (
        ("每日 CIO 简报", "brief", "overview", views.brief),
        ("组合持仓", "portfolio", "pie_chart", views.portfolio),
        ("交易计划", "plans", "list_alt", views.plans),
        ("订单草稿", "drafts", "rule", views.drafts),
        ("投资日志", "journal", "book", views.journal),
        ("绩效复盘", "performance", "monitoring", views.performance),
        ("设置", "settings", "settings", views.settings),
    )
    page = st.navigation(
        [
            st.Page(
                partial(view, data),
                title=label,
                url_path=path,
                icon=f":material/{icon}:",
            )
            for label, path, icon, view in pages
        ]
    )
    st.sidebar.divider()
    st.sidebar.caption("本地模式 · 订单提交关闭")
    try:
        page.run()
    except FileNotFoundError:
        st.info("未找到已初始化的 DuckDB。")
    except DuckDBError:
        st.error("无法读取 DuckDB。数据库可能未初始化，或正由其他流程占用。")
    except (OSError, ValueError, YAMLError, KeyError):
        st.error("本地数据或配置无法读取。")


if __name__ == "__main__":
    main()
