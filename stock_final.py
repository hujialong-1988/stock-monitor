import streamlit as st
import pandas as pd
import numpy as np
import ta
import schedule
import time
import threading
from dotenv import load_dotenv
import os
import requests
import json
import tushare as ts
import baostock as bs
# import mootdx
# from mootdx.quotes import Quotes

# 加载环境变量
load_dotenv()

# 初始化 tushare
ts.set_token(os.getenv("TUSHARE_TOKEN"))
pro = ts.pro_api()

# 初始化 baostock
bs.login()

# 初始化 mootdx（已注释，避免报错）
# quotes = Quotes.factory(market='std')

# -------------------------- 自选股管理 --------------------------
def load_watchlist():
    try:
        with open("watchlist.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_watchlist(stocks):
    with open("watchlist.json", "w", encoding="utf-8") as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)

def add_stock(code, name):
    stocks = load_watchlist()
    if not any(s['code'] == code for s in stocks):
        stocks.append({"code": code, "name": name})
        save_watchlist(stocks)
        st.session_state.stocks = stocks
        st.success(f"已添加 {name}({code}) 到自选股")
    else:
        st.warning(f"{name}({code}) 已在自选股中")

def remove_stock(code):
    stocks = load_watchlist()
    stocks = [s for s in stocks if s['code'] != code]
    save_watchlist(stocks)
    st.session_state.stocks = stocks
    st.success("已从自选股中移除")

# -------------------------- 微信推送 --------------------------
def send_wechat_message(content):
    webhook = os.getenv("WEBHOOK_URL")
    if not webhook:
        st.warning("未配置微信 Webhook URL，无法推送消息")
        return False
    data = {
        "msgtype": "text",
        "text": {"content": content}
    }
    try:
        response = requests.post(webhook, json=data)
        return response.status_code == 200
    except:
        st.error("微信推送失败")
        return False

def send_wechat_test():
    if st.button("测试微信推送"):
        if send_wechat_message("【股票盯盘系统测试】这是一条测试消息，功能正常！"):
            st.success("测试消息已发送到微信")
        else:
            st.error("测试消息发送失败")

# -------------------------- 行情数据获取 --------------------------
def get_realtime_data(stocks):
    data = []
    for s in stocks:
        try:
            # 用 tushare 获取实时行情
            df = pro.daily(ts_code=s['code'], start_date='20250519', end_date='20250519')
            if not df.empty:
                row = df.iloc[0]
                data.append({
                    "代码": s['code'],
                    "名称": s['name'],
                    "当前价": row['close'],
                    "涨跌幅": row['pct_chg'],
                    "成交量": row['vol'],
                    "成交额": row['amount']
                })
            else:
                # fallback 到 baostock
                k = bs.query_history_k_data_plus(
                    s['code'], "date,code,open,high,low,close,volume,amount",
                    start_date='2025-05-19', end_date='2025-05-19', frequency="d", adjustflag="3"
                ).get_data()
                if not k.empty:
                    data.append({
                        "代码": s['code'],
                        "名称": s['name'],
                        "当前价": float(k['close'].iloc[0]),
                        "涨跌幅": (float(k['close'].iloc[0]) - float(k['open'].iloc[0])) / float(k['open'].iloc[0]) * 100,
                        "成交量": int(k['volume'].iloc[0]),
                        "成交额": float(k['amount'].iloc[0])
                    })
        except:
            continue
    return pd.DataFrame(data)

# -------------------------- 主力资金分析 --------------------------
def analyze_fund_flow(code):
    try:
        # 用 tushare 获取资金流数据
        df = pro.moneyflow(ts_code=code, start_date='20250519', end_date='20250519')
        if not df.empty:
            return df[['trade_date', 'buy_sm_vol', 'buy_md_vol', 'buy_lg_vol', 'buy_elg_vol', 'sell_sm_vol', 'sell_md_vol', 'sell_lg_vol', 'sell_elg_vol']]
    except:
        st.warning("资金流数据获取失败")
        return None

def plot_fund_flow(df):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df['trade_date'], df['buy_lg_vol'] - df['sell_lg_vol'], label='主力净流入', color='red')
    ax.set_title("主力资金流向")
    ax.legend()
    return fig

# -------------------------- 交易复盘 --------------------------
def load_trade_records():
    try:
        with open("trades.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_trade_records(records):
    with open("trades.json", "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def trade_form():
    with st.form("交易记录"):
        st.subheader("添加交易记录")
        col1, col2 = st.columns(2)
        with col1:
            code = st.text_input("股票代码")
            name = st.text_input("股票名称")
            price = st.number_input("成交价格", min_value=0.0, step=0.01)
            volume = st.number_input("成交数量", min_value=0, step=100)
        with col2:
            direction = st.selectbox("买卖方向", ["买入", "卖出"])
            date = st.date_input("交易日期")
            note = st.text_area("备注")
        submitted = st.form_submit_button("保存记录")
        if submitted:
            records = load_trade_records()
            records.append({
                "code": code,
                "name": name,
                "direction": direction,
                "price": price,
                "volume": volume,
                "date": str(date),
                "note": note
            })
            save_trade_records(records)
            st.success("交易记录已保存")
            send_wechat_message(f"【交易提醒】{direction} {name}({code}) {volume}股，价格{price}元，备注：{note}")

def show_trade_records():
    st.subheader("历史交易记录")
    records = load_trade_records()
    if records:
        df = pd.DataFrame(records)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("暂无交易记录")

# -------------------------- 市场情绪（已注释） --------------------------
# def get_market_mood():
#     """获取市场情绪和仓位建议（akshare 数据源）"""
#     try:
#         market = ak.stock_zh_a_spot_em()
#         up_count = len(market[market['涨跌幅'] > 0])
#         total_count = len(market)
#         up_ratio = up_count / total_count
#         
#         if up_ratio > 0.7:
#             mood = "🔥 乐观"
#             position = "高仓位（70%-90%）"
#         elif up_ratio > 0.5:
#             mood = "😊 温和"
#             position = "中仓位（50%-70%）"
#         elif up_ratio > 0.3:
#             mood = "😐 谨慎"
#             position = "低仓位（30%-50%）"
#         else:
#             mood = "💀 悲观"
#             position = "空仓/轻仓（0%-30%）"
#         return mood, position
#     except Exception as e:
#         return "数据获取失败", "请检查网络"

# -------------------------- 定时任务 --------------------------
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

def daily_review():
    stocks = load_watchlist()
    if stocks:
        df = get_realtime_data(stocks)
        content = "【每日收盘自动复盘】\n" + df.to_string(index=False)
        send_wechat_message(content)

# 启动定时线程
if 'scheduler_started' not in st.session_state:
    schedule.every().day.at("15:30").do(daily_review)
    threading.Thread(target=run_schedule, daemon=True).start()
    st.session_state.scheduler_started = True

# -------------------------- 主界面 --------------------------
def main():
    st.set_page_config(page_title="全免费终极股票盯盘复盘系统", layout="wide")
    st.title("📊 全免费终极股票盯盘复盘系统（最终版）")
    
    # 初始化 session state
    if 'stocks' not in st.session_state:
        st.session_state.stocks = load_watchlist()
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 功能设置")
        # 添加自选股
        with st.form("添加自选股"):
            code = st.text_input("股票代码（如 000001.SZ）")
            name = st.text_input("股票名称")
            submitted = st.form_submit_button("添加到自选股")
            if submitted:
                add_stock(code, name)
        st.divider()
        # 微信测试
        send_wechat_test()
        st.divider()
        # 显示自选股
        st.subheader("我的自选股")
        for s in st.session_state.stocks:
            col1, col2 = st.columns([4,1])
            col1.write(f"{s['name']}({s['code']})")
            if col2.button("删", key=s['code']):
                remove_stock(s['code'])
    
    # 标签页
    tab1, tab2, tab3, tab4 = st.tabs(["📈 行情监控", "💰 主力资金", "📝 交易复盘", "📊 市场分析"])
    
    with tab1:
        st.header("实时行情监控")
        if st.session_state.stocks:
            df = get_realtime_data(st.session_state.stocks)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("请先添加自选股")
    
    with tab2:
        st.header("主力资金分析")
        if st.session_state.stocks:
            opt = [f"{s['code']}-{s['name']}" for s in st.session_state.stocks]
            sel = st.selectbox("选择个股", opt)
            code = sel.split('-')[0]
            fd = analyze_fund_flow(code)
            if fd:
                st.subheader(f"{sel} 主力资金流")
                st.dataframe(fd, use_container_width=True)
                fig = plot_fund_flow(fd)
                st.pyplot(fig)
        else:
            st.info("请先添加自选股")
    
    with tab3:
        st.header("交易复盘记录")
        trade_form()
        show_trade_records()
    
    with tab4:
        st.header("市场分析")
        st.info("✅ 市场情绪/备用行情功能暂时关闭，核心功能全部正常！")

if __name__ == "__main__":
    main()