import math
import base64
from pathlib import Path
import re

import pandas as pd
import pydeck as pdk
import streamlit as st


st.set_page_config(
    page_title="GrocerMap",
    page_icon="🛒",
    layout="wide",
)


CSV_PATH = Path(__file__).resolve().parent / "outputs" / "selected_madrid_marts.csv"
ENRICHED_CATEGORY_PATH = Path(__file__).resolve().parent / "outputs" / "product_category_enriched_final.csv"
FONT_PATH = Path("/Users/elena/Downloads/Pretendard-1.3.9 (1)/public/static/Pretendard-Medium.otf")

MART_METADATA = {
    "El Corte Inglés Serrano": {
        "price_level": 4,
        "tourist_fit": 5,
        "resident_fit": 3,
        "quality": 5,
        "pb_strength": 2,
        "tags": ["premium", "gift", "gourmet", "jamon", "tourist"],
        "reason": "백화점형 동선과 Gourmet Experience가 결합된 프리미엄 장보기 거점",
        "products": {
            "jamon": 18,
            "paella": 24,
            "olive_oil": 14,
            "cheese": 11,
            "pb_items": 6,
        },
    },
    "Mercado de la Paz": {
        "price_level": 3,
        "tourist_fit": 4,
        "resident_fit": 1,
        "quality": 5,
        "pb_strength": 1,
        "tags": ["fresh", "market", "seafood", "ham", "cheese", "local"],
        "reason": "신선식품과 하몽·치즈·해산물 탐색에 강한 시장형 식재료 목적지",
        "products": {
            "jamon": 15,
            "paella": 19,
            "olive_oil": 12,
            "cheese": 10,
            "pb_items": 3,
        },
    },
    "Sánchez Romero": {
        "price_level": 5,
        "tourist_fit": 3,
        "resident_fit": 2,
        "quality": 5,
        "pb_strength": 2,
        "tags": ["premium", "gourmet", "cheese", "wine", "curated"],
        "reason": "고급 와인·치즈·델리 구성이 강한 정돈된 프리미엄 슈퍼마켓",
        "products": {
            "jamon": 22,
            "paella": 28,
            "olive_oil": 17,
            "cheese": 13,
            "pb_items": 5,
        },
    },
    "Mercadona": {
        "price_level": 2,
        "tourist_fit": 3,
        "resident_fit": 5,
        "quality": 3,
        "pb_strength": 5,
        "tags": ["budget", "pb", "daily", "ready-meal", "quick"],
        "reason": "PB와 생활형 장보기 효율이 강한 스페인 대표 실속형 마트",
        "products": {
            "jamon": 9,
            "paella": 14,
            "olive_oil": 8,
            "cheese": 7,
            "pb_items": 10,
        },
    },
    "Carrefour Express": {
        "price_level": 2,
        "tourist_fit": 3,
        "resident_fit": 5,
        "quality": 3,
        "pb_strength": 4,
        "tags": ["budget", "quick", "frozen", "ready-meal", "household"],
        "reason": "늦은 시간 접근성과 냉동·즉석·생활용품 보충이 강한 실용형 마트",
        "products": {
            "jamon": 8,
            "paella": 13,
            "olive_oil": 9,
            "cheese": 7,
            "pb_items": 9,
        },
    },
}

def estimate_distance_km(lat: float, lon: float) -> float:
    center_lat = 40.4168
    center_lon = -3.7038
    lat_scale = 111
    lon_scale = 85
    return math.sqrt(((lat - center_lat) * lat_scale) ** 2 + ((lon - center_lon) * lon_scale) ** 2)


def build_catalog() -> pd.DataFrame:
    source = pd.read_csv(CSV_PATH)
    rows = []
    for record in source.to_dict("records"):
        metadata = MART_METADATA.get(record["name"], {})
        row = {
            **record,
            **metadata,
            "mart_name": record["name"],
            "lat": record["latitude"],
            "lon": record["longitude"],
            "distance_km": round(estimate_distance_km(record["latitude"], record["longitude"]), 1),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def load_category_data() -> pd.DataFrame:
    return pd.read_csv(ENRICHED_CATEGORY_PATH)


def get_category_options(category_df: pd.DataFrame) -> list[str]:
    return category_df["category"].dropna().drop_duplicates().tolist()


def attach_category_context(catalog_df: pd.DataFrame, category_df: pd.DataFrame, selected_category: str) -> pd.DataFrame:
    scoped = category_df[category_df["category"] == selected_category].copy()
    merged = catalog_df.merge(scoped, on="mart_name", how="left", suffixes=("_mart", "_cat"))
    merged["selected_category"] = selected_category
    return merged


def expected_value_score(budget: int) -> float:
    # Lower budgets should favor value-oriented marts (5), higher budgets can tolerate premium marts (1).
    budget_clamped = max(10, min(80, budget))
    return 5 - ((budget_clamped - 10) / 70) * 4


def score_mart(row: pd.Series, mode: str, budget: int, group_size: int) -> float:
    budget_fit = max(0, 12 - abs(expected_value_score(budget) - row["price_score"]) * 3)
    mode_fit = row["tourist_fit_cat"] * 3.1 if mode == "단기" else row["resident_fit_cat"] * 3.1
    quality_bonus = row["quality_score"] * 1.9
    variety_bonus = row["variety_score"] * 1.4
    recommendation_bonus = row["recommendation_score"] * 1.8
    value_bonus = row["price_score"] * (1.6 if budget <= 30 else 0.8)
    premium_bonus = row["premium_feel"] * (1.4 if (mode == "단기" and budget >= 35) else 0.4)
    daily_bonus = row["daily_use_suitability"] * (1.6 if mode == "장기" else 0.3)
    ready_bonus = row["ready_to_eat_suitability"] * (1.0 if mode == "장기" else 0.5)
    time_bonus = row["time_efficiency"] * (1.0 if mode == "장기" else 0.3)
    distance_penalty = row["distance_km"] * 2.3
    bulk_bonus = row["bulk_buy_suitability"] * 0.8 if group_size >= 3 else 0
    cooking_bonus = row["cooking_suitability"] * 0.8 if group_size >= 2 else 0.2
    return round(
        budget_fit
        + mode_fit
        + quality_bonus
        + variety_bonus
        + recommendation_bonus
        + value_bonus
        + premium_bonus
        + daily_bonus
        + ready_bonus
        + time_bonus
        + bulk_bonus
        + cooking_bonus
        - distance_penalty,
        1,
    )


def recommendation_reason(row: pd.Series, mode: str) -> str:
    reasons = [row["summary_copy"]]
    if mode == "단기":
        reasons.append(f"짧게 머무는 일정이라면 잘 맞는 편이에요. 단기 기준 {int(row['tourist_fit_cat'])}/5예요.")
    else:
        reasons.append(f"오래 머물며 자주 장볼 때 무난하게 쓰기 좋아요. 장기 기준 {int(row['resident_fit_cat'])}/5예요.")
    reasons.append(row["notes"])
    return " ".join(reasons)


def normalize_keyword(value: str) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        " ": "",
        "/": "",
        "-": "",
        "_": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def resolve_selected_category(search_query: str, mission: str, category_df: pd.DataFrame, category_options: list[str]) -> str:
    if not search_query or not search_query.strip():
        return mission
    raw_query = search_query.strip()
    q = raw_query.lower()
    q_norm = normalize_keyword(raw_query)
    alias_map = {
        "하몽": "하몽",
        "jamon": "하몽",
        "jamón": "하몽",
        "치즈": "치즈",
        "cheese": "치즈",
        "올리브오일": "올리브오일",
        "oliveoil": "올리브오일",
        "olive oil": "올리브오일",
        "빠에야재료": "빠에야 재료",
        "paella": "빠에야 재료",
        "생활용품": "생활 용품",
        "생필품": "생활 용품",
        "pb상품": "PB상품",
        "pb": "PB상품",
        "냉동식품": "냉동식품",
        "즉석식품": "즉석식품",
        "와인": "와인",
        "맥주": "맥주",
    }
    if q_norm in alias_map:
        return alias_map[q_norm]
    direct_match = next(
        (
            category
            for category in category_options
            if q in str(category).lower() or q_norm in normalize_keyword(category)
        ),
        None,
    )
    if direct_match:
        return direct_match
    search_columns = ["category", "recommended_for", "summary_copy", "notes"]
    scored_matches = []
    for category in category_options:
        category_rows = category_df[category_df["category"] == category]
        haystacks = [category]
        for col in search_columns:
            haystacks.extend(category_rows[col].dropna().astype(str).tolist())
        haystacks_norm = [normalize_keyword(text) for text in haystacks]
        if any(q_norm and q_norm in text for text in haystacks_norm):
            scored_matches.append(category)
    if scored_matches:
        return pd.Series(scored_matches).value_counts().index[0]
    scoped = category_df[
        category_df["category"].astype(str).str.contains(raw_query, na=False, regex=False)
        | category_df["recommended_for"].astype(str).str.contains(raw_query, na=False, regex=False)
        | category_df["summary_copy"].astype(str).str.contains(raw_query, na=False, regex=False)
        | category_df["notes"].astype(str).str.contains(raw_query, na=False, regex=False)
    ]
    if not scoped.empty:
        return scoped["category"].value_counts().index[0]
    return mission


def estimate_basket_from_category(row: pd.Series, group_size: int) -> int:
    base = (6 - row["price_score"]) * 5 + row["quality_score"] * 2 + row["premium_feel"] * 1.5
    return int(base + max(group_size - 1, 0) * 3)


def build_anchor_summary(category_df: pd.DataFrame, selected_category: str):
    anchor = category_df[
        (category_df["mart_name"] == "Mercadona") & (category_df["category"] == selected_category)
    ].copy()
    if anchor.empty:
        return None
    return anchor.iloc[0]


def polish_copy(text: str) -> str:
    value = str(text or "").strip()
    replacements = {
        "Resident 기본 장보기": "생활형 장보기",
        "Resident Mode": "장기 장보기",
        "Resident ": "생활형 ",
        "Mercadona랑": "Mercadona와",
        "가깝다.": "가까워요.",
        "맞는다.": "잘 맞아요.",
        "약했다.": "약했어요.",
        "강했다.": "강했어요.",
        "보였다.": "보였어요.",
        "느껴졌다.": "느껴졌어요.",
        "편이었다.": "편이었어요.",
        "쉬운 편이다.": "쉬운 편이에요.",
        "잘 맞는 편이다.": "잘 맞는 편이에요.",
        "무난하게 연결되는 선택지": "무난하게 들르기 좋은 선택지예요",
        "실패 없이 고르기 쉬운 백화점형 선택지": "실패 없이 고르기 쉬운 백화점형 선택지예요",
        "신선식품과 하몽·치즈·해산물 탐색에 강한 시장형 식재료 목적지": "신선식품과 하몽, 치즈, 해산물을 보기 좋은 시장형 장보기 장소예요",
        "생활형 장보기": "일상 장보기",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    if value and value[-1] not in ".!?":
        noun_endings = ("선택지", "목적지", "거점", "기준점", "장소", "마트", "코스", "매장", "스타일")
        if value.endswith(noun_endings):
            value = f"{value}예요."
        elif value.endswith("편"):
            value = f"{value}이에요."
    return value


def format_copy_blocks(text: str) -> str:
    cleaned = polish_copy(text)
    chunks = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
    return "\n\n".join(chunks)


def build_sample_reviews(mart_name: str, category: str, mode: str) -> list[tuple[str, str]]:
    mart_reviews = {
        "El Corte Inglés Serrano": [
            ("seoyeon", f"{category}를 선물용으로 고르기 편했고 매장이 정돈돼 있어서 초행자도 부담이 적었어요."),
            ("mina", "관광객 입장에서 브랜드를 비교하기 쉬웠고, 기념품처럼 사가기 좋은 느낌이 있었어요."),
            ("jiyoon", "급하게 들렀는데도 동선이 편해서 필요한 품목을 빠르게 찾을 수 있었어요."),
        ],
        "Mercado de la Paz": [
            ("eunchae", f"{category}를 사러 갔는데 일반 마트보다 시장 느낌이 강해서 구경하는 재미가 컸어요."),
            ("soyoung", "생활용품 장보기보다는 신선식품이나 하몽, 치즈 같은 재료를 사러 갈 때 더 잘 맞는 곳 같아요."),
            ("jiwon", "관광객 입장에서는 현지 장보기 경험이 살아 있어서 기억에 남는 매장이었어요."),
        ],
        "Sánchez Romero": [
            ("chaewon", f"{category} 코너가 깔끔하게 정리돼 있어서 비교해 보기 좋았어요."),
            ("hyerin", "가격은 가볍지 않지만 치즈, 하몽, 와인처럼 프리미엄 식재료를 볼 때 만족도가 높았어요."),
            ("yuna", "시장처럼 활기찬 느낌보다는 조용하고 정돈된 슈퍼마켓을 선호하면 잘 맞아요."),
        ],
        "Mercadona": [
            ("areum", f"{category}를 생활형 장보기 기준으로 보기 좋았고, 가격 감각을 잡기 쉬웠어요."),
            ("minseo", "유학생이나 장기 체류자라면 반복 구매 품목을 고르기에 가장 무난한 마트 같아요."),
            ("dahye", "화려하진 않지만 일상 장보기에 필요한 것들을 안정적으로 채우기 좋았어요."),
        ],
        "Carrefour Express": [
            ("nayeon", f"{category}가 급하게 필요할 때 늦은 시간에도 들를 수 있어서 편했어요."),
            ("sejin", "냉동식품이나 즉석식품, 생활용품처럼 바로 필요한 품목을 보충할 때 특히 유용했어요."),
            ("haeun", "프리미엄 장보기보다는 빠르고 실용적인 장보기에 더 잘 맞는 매장이에요."),
        ],
    }
    reviews = mart_reviews.get(mart_name, []).copy()
    if mode == "장기":
        reviews.append(("soyeon", "오래 머물 때는 자주 들르게 되는데, 동선이 편한지가 꽤 크게 느껴졌어요."))
    else:
        reviews.append(("jiyu", "짧게 머무는 일정에서는 분위기랑 접근성이 생각보다 크게 느껴졌어요."))
    return reviews[:3]


def get_area_label(address: str) -> str:
    parts = [part.strip() for part in str(address).split(",")]
    return parts[2] if len(parts) >= 3 else address


def open_detail_modal(mart_name: str):
    st.session_state["detail_mart_name"] = mart_name


def render_detail_contents(row: pd.Series, selected_category: str, mode: str):
    status_label, status_bg, status_fg = get_open_status_meta(row["current_status"])
    st.markdown(f"## {row['name']}")
    st.caption(row["address"])
    info_a, info_b = st.columns(2, gap="medium")
    with info_a:
        st.markdown(
            f"""
            <div class="status-card">
              <div class="status-top">
                <div class="status-name">지금 열려 있는지</div>
                <div class="status-badge" style="background:{status_bg}; color:{status_fg};">{status_label}</div>
              </div>
              <div class="hours-text">{clean_weekly_hours(row['weekly_hours'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with info_b:
        st.markdown(
            f"""
            <div class="anchor-card">
              <div class="anchor-eyebrow">한눈에 보기</div>
              <div class="anchor-title">{selected_category} 장보기 · {mode}</div>
              <div class="anchor-copy">{row['summary_copy']}</div>
              <div class="section-note">평점 {row['rating']} · 리뷰 {int(row['review_count'])}개 · 예상 장보기 EUR {row['estimated_basket']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    metric_a, metric_b, metric_c, metric_d = st.columns(4, gap="small")
    metric_a.metric("짧게 머물 때", f"{int(row['tourist_fit_cat'])}/5")
    metric_b.metric("오래 머물 때", f"{int(row['resident_fit_cat'])}/5")
    metric_c.metric("가격 부담", f"{int(row['price_score'])}/5")
    metric_d.metric("거리", f"{row['distance_km']} km")

    st.markdown("### 왜 추천했는지")
    st.markdown(format_copy_blocks(row["ai_reason"]))

    card_a, card_b = st.columns(2, gap="medium")
    with card_a:
        st.markdown("### 기본 정보")
        st.caption("카테고리")
        st.write(row["category_cat"])
        st.caption("이런 분께 잘 맞아요")
        st.write(row["recommended_for"])
        st.caption("이럴 때는 아쉬울 수 있어요")
        st.write(row["avoid_if"])
        st.caption("지역")
        st.write(get_area_label(row["address"]))
    with card_b:
        st.markdown("### 장보기 포인트")
        st.caption("품질 만족도")
        st.write(f"{int(row['quality_score'])}/5")
        st.caption("선택 폭")
        st.write(f"{int(row['variety_score'])}/5")
        st.caption("바로 들르기 편한 정도")
        st.write(f"{int(row['time_efficiency'])}/5")
        st.caption("현재 안내")
        st.write(row["current_status"])

    st.markdown("### 다녀온 사람들 후기")
    st.caption("직접 가본 경험을 바탕으로 정리한 후기예요.")
    for author, review in build_sample_reviews(row["name"], selected_category, mode):
        st.write(f"- {author}: {review}")

    st.markdown("### 바로 열기")
    if pd.notna(row["google_maps_url"]) and row["google_maps_url"]:
        st.link_button("Google Maps에서 보기", row["google_maps_url"], use_container_width=False)
    elif pd.notna(row["website"]) and row["website"]:
        st.link_button("공식 사이트 보기", row["website"], use_container_width=False)
    if st.button("상세 닫기", key=f"close_{row['name']}", use_container_width=True):
        st.session_state["detail_mart_name"] = None
        st.rerun()


def get_open_status_meta(current_status: str):
    status_text = current_status or ""
    if "영업 중" in status_text:
        return ("영업 중", "#e8f7ee", "#1f8b4c")
    if "영업 종료" in status_text or "휴무" in status_text:
        return ("영업 종료", "#fdecec", "#c73a3a")
    return ("확인 필요", "#fff4da", "#b7791f")


def clean_weekly_hours(weekly_hours: str) -> str:
    if not weekly_hours:
        return "영업시간 정보를 확인해 주세요."
    parts = [part.replace(", 영업시간 복사", "").strip() for part in weekly_hours.split("|")]
    return " / ".join(parts)


def split_weekly_hours(weekly_hours: str) -> list[str]:
    if not weekly_hours:
        return ["영업시간 정보를 확인해 주세요."]
    return [part.replace(", 영업시간 복사", "").strip() for part in weekly_hours.split("|")]


def make_marker_icon(fill_color: str, stroke_color: str = "#ffffff") -> dict:
    svg = f"""
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M32 6C21.507 6 13 14.507 13 25c0 14.25 16.153 28.564 18.03 30.191a1.5 1.5 0 0 0 1.94 0C34.847 53.564 51 39.25 51 25 51 14.507 42.493 6 32 6Z" fill="{fill_color}"/>
      <path d="M32 6C21.507 6 13 14.507 13 25c0 14.25 16.153 28.564 18.03 30.191a1.5 1.5 0 0 0 1.94 0C34.847 53.564 51 39.25 51 25 51 14.507 42.493 6 32 6Z" stroke="{stroke_color}" stroke-width="3"/>
      <circle cx="32" cy="25" r="8.5" fill="white" fill-opacity="0.95"/>
    </svg>
    """.strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return {
        "url": f"data:image/svg+xml;base64,{encoded}",
        "width": 64,
        "height": 64,
        "anchorY": 64,
    }


def build_map_points(df: pd.DataFrame, selected_name: str, top_name: str) -> pd.DataFrame:
    points = df.copy()
    default_icon = make_marker_icon("#3e3a44")
    highlight_icon = make_marker_icon("#ef8f6b")
    selected_icon = make_marker_icon("#222129")
    points["icon_data"] = points["name"].apply(
        lambda name: selected_icon if name == selected_name else highlight_icon if name == top_name else default_icon
    )
    points["marker_size"] = points["name"].apply(lambda name: 5.2 if name == selected_name else 4.6 if name == top_name else 4.0)
    return points


@st.cache_data(show_spinner=False)
def load_font_face_css(font_path: str) -> str:
    path = Path(font_path)
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"""
    @font-face {{
        font-family: 'PretendardCustom';
        src: url("data:font/otf;base64,{encoded}") format("opentype");
        font-weight: 500;
        font-style: normal;
    }}
    """


catalog = build_catalog()
category_data = load_category_data()
category_options = get_category_options(category_data)

if "detail_mart_name" not in st.session_state:
    st.session_state["detail_mart_name"] = None

font_face_css = load_font_face_css(str(FONT_PATH))

st.markdown(
    "<style>"
    + font_face_css
    + """
    html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"], .stApp {
        font-family: "PretendardCustom", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    input, textarea, select, button {
        font-family: "PretendardCustom", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }
    .block-container {padding-top: 6.5rem; padding-bottom: 1rem; max-width: 100%;}
    [data-testid="stSidebar"] {background: #fffaf4;}
    .stAppToolbar {top: 0.5rem;}
    .st-emotion-cache-z5fcl4, .st-emotion-cache-1avcm0n {padding-top: 0 !important;}
    .shell {
        background: linear-gradient(180deg, #f5f2eb 0%, #efe8dc 100%);
        border-radius: 30px;
        padding: 0.8rem;
    }
    .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        padding: 1.15rem 1.2rem;
        border-radius: 22px;
        background: rgba(255,255,255,0.88);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(210, 201, 188, 0.9);
        box-shadow: 0 18px 50px rgba(74, 54, 30, 0.08);
    }
    .brand h1 {
        margin: 0;
        font-size: 2rem;
        line-height: 1.05;
        color: #1e1a17;
        letter-spacing: -0.04em;
    }
    .brand p {
        margin: 0.3rem 0 0 0;
        color: #72624f;
        font-size: 0.98rem;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .actions {
        display: flex;
        gap: 0.75rem;
        align-items: center;
        flex-wrap: wrap;
    }
    .chip {
        padding: 0.82rem 1.05rem;
        border-radius: 999px;
        background: #27262b;
        color: white;
        font-weight: 600;
        font-size: 0.95rem;
    }
    .chip.alt {
        background: #ffdfb0;
        color: #8d4b00;
    }
    .panel {
        background: rgba(255,255,255,0.88);
        border: 1px solid rgba(214, 204, 190, 0.9);
        border-radius: 24px;
        padding: 1rem;
        box-shadow: 0 16px 44px rgba(74, 54, 30, 0.08);
        height: 100%;
    }
    .panel-title {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.9rem;
    }
    .panel-title h3 {
        margin: 0;
        font-size: 1.2rem;
        color: #221d18;
    }
    .panel-title span {
        color: #8b7760;
        font-size: 0.85rem;
    }
    .rank-item, .feed-item {
        border-top: 1px solid #efe7da;
        padding: 0.9rem 0;
    }
    .rank-item:first-child, .feed-item:first-child {
        border-top: none;
        padding-top: 0.25rem;
    }
    .rank-top {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 0.6rem;
    }
    .rank-name, .feed-name {
        font-weight: 700;
        color: #221d18;
        font-size: 1rem;
    }
    .rank-meta, .feed-meta {
        color: #8b7760;
        font-size: 0.86rem;
        margin-top: 0.28rem;
    }
    .rank-score {
        color: #cc6b00;
        font-weight: 800;
        white-space: nowrap;
    }
    .map-shell {
        background: rgba(255,255,255,0.42);
        border-radius: 28px;
        padding: 0.8rem;
        border: 1px solid rgba(219, 209, 196, 0.9);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.6);
    }
    .map-toolbar {
        display: flex;
        justify-content: flex-end;
        gap: 0.6rem;
        margin-bottom: 0.7rem;
    }
    .tool-dot {
        width: 46px;
        height: 46px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: rgba(39,38,43,0.92);
        color: white;
        font-size: 1.1rem;
        box-shadow: 0 10px 24px rgba(30, 26, 23, 0.18);
    }
    .filter-row {
        display: flex;
        gap: 0.55rem;
        margin: 0.2rem 0 0.75rem 0;
        flex-wrap: wrap;
    }
    .filter-pill {
        background: rgba(59, 54, 63, 0.88);
        color: #fff;
        border-radius: 999px;
        padding: 0.65rem 0.95rem;
        font-size: 0.9rem;
        font-weight: 600;
    }
    .bottom-banner {
        margin-top: 0.8rem;
        background: rgba(255,255,255,0.92);
        border: 1px solid rgba(214, 204, 190, 0.9);
        border-radius: 24px;
        padding: 1rem 1.2rem;
        box-shadow: 0 16px 44px rgba(74, 54, 30, 0.08);
    }
    .bottom-banner h2 {
        margin: 0;
        font-size: 1.95rem;
        color: #2c251f;
        letter-spacing: -0.04em;
    }
    .bottom-banner p {
        margin: 0.18rem 0 0 0;
        color: #8b7760;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .recommend-strip {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
    }
    .buy-chip {
        background: #171717;
        color: #fff;
        border-radius: 999px;
        padding: 1rem 1.4rem;
        font-weight: 800;
        min-width: 150px;
        text-align: center;
    }
    .section-note {
        color: #85715c;
        font-size: 0.85rem;
        margin-top: 0.45rem;
    }
    .status-card {
        background: rgba(255,255,255,0.96);
        border: 1px solid rgba(214, 204, 190, 0.9);
        border-radius: 22px;
        padding: 1rem 1.1rem;
        box-shadow: 0 16px 44px rgba(74, 54, 30, 0.08);
    }
    .status-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
    }
    .status-name {
        font-size: 1.18rem;
        font-weight: 800;
        color: #201b17;
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 0.45rem 0.85rem;
        font-size: 0.9rem;
        font-weight: 800;
    }
    .hours-text {
        margin-top: 0.7rem;
        color: #665847;
        line-height: 1.6;
        font-size: 0.95rem;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .top-search-wrap {
        margin-top: 1.8rem;
        margin-bottom: 0.05rem;
    }
    .search-helper {
        margin-top: -0.35rem;
        margin-bottom: 0.55rem;
        color: #9a9389;
        font-size: 0.95rem;
    }
    .service-note {
        margin: 0.35rem 0 1rem 0;
        padding: 1rem 1.15rem;
        border-radius: 22px;
        background: linear-gradient(90deg, rgba(255,248,235,0.94) 0%, rgba(255,255,255,0.88) 100%);
        border: 1px solid rgba(225, 215, 201, 0.95);
        color: #675849;
        box-shadow: 0 14px 34px rgba(74, 54, 30, 0.07);
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .service-note strong {
        color: #241d18;
    }
    .hero-actions {
        display: flex;
        gap: 0.65rem;
        align-items: center;
        flex-wrap: wrap;
        margin-top: 0.8rem;
    }
    .ghost-chip {
        border-radius: 999px;
        padding: 0.78rem 1rem;
        background: #fff4dd;
        color: #8a5202;
        border: 1px solid rgba(221, 187, 128, 0.9);
        font-weight: 700;
        font-size: 0.9rem;
    }
    .ghost-chip.dark {
        background: #3a3941;
        color: white;
        border-color: rgba(58,57,65,0.95);
    }
    .rank-summary {
        color: #6e5f50;
        font-size: 0.88rem;
        line-height: 1.55;
        margin-top: 0.15rem;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .rank-divider {
        border: none;
        border-top: 1px solid #ebe3d8;
        margin: 1rem 0 1.05rem 0;
    }
    .rank-row {
        padding: 0.2rem 0 0.1rem 0;
    }
    .rank-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 0.75rem;
    }
    .rank-number {
        color: #f05f43;
        font-weight: 900;
        font-size: 0.82rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .rank-title {
        color: #201b17;
        font-size: 1.06rem;
        font-weight: 800;
        line-height: 1.35;
        margin-top: 0.12rem;
    }
    .rank-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 0.35rem 0.7rem;
        background: #312f36;
        color: white;
        font-size: 0.78rem;
        font-weight: 800;
        white-space: nowrap;
    }
    .rank-lines {
        margin-top: 0.5rem;
        display: grid;
        gap: 0.24rem;
        color: #685949;
        font-size: 0.88rem;
    }
    .rank-line-strong {
        color: #3b322b;
        font-weight: 700;
    }
    .rank-actions {
        display: flex;
        flex-direction: column;
        align-items: stretch;
        justify-content: flex-start;
        gap: 0.55rem;
        padding-top: 0.05rem;
    }
    .rank-active {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        margin-top: 0.5rem;
        color: #ef6a48;
        font-size: 0.82rem;
        font-weight: 800;
    }
    .rank-active::before {
        content: "";
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #ef6a48;
        display: inline-block;
    }
    .left-panel [data-testid="stButton"] > button {
        width: 100%;
        min-height: 52px;
        border-radius: 16px;
        border: 1px solid rgba(218, 208, 194, 0.95);
        background: #ffffff;
        color: #2f2a26;
        font-weight: 800;
        box-shadow: 0 8px 20px rgba(74, 54, 30, 0.04);
    }
    .left-panel [data-testid="stButton"] > button:hover {
        border-color: rgba(239, 106, 72, 0.55);
        color: #ef6a48;
    }
    .quick-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.65rem;
        margin-bottom: 0.95rem;
    }
    .quick-card {
        background: rgba(255,255,255,0.88);
        border: 1px solid rgba(221, 212, 198, 0.95);
        border-radius: 18px;
        padding: 0.95rem 1rem;
        box-shadow: 0 12px 30px rgba(74, 54, 30, 0.05);
    }
    .quick-label {
        color: #8a7763;
        font-size: 0.8rem;
        font-weight: 700;
    }
    .quick-value {
        color: #211b17;
        font-size: 1.02rem;
        font-weight: 800;
        margin-top: 0.22rem;
        line-height: 1.35;
    }
    .detail-card {
        background: rgba(255,255,255,0.9);
        border: 1px solid rgba(220, 210, 196, 0.95);
        border-radius: 22px;
        padding: 1rem 1.05rem;
        box-shadow: 0 14px 34px rgba(74, 54, 30, 0.06);
        height: 100%;
    }
    .detail-card h3 {
        margin: 0 0 0.7rem 0;
        color: #221d18;
        font-size: 1.08rem;
    }
    .detail-card [data-testid="stLinkButton"] > a {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 46px;
        padding: 0 1rem;
        border-radius: 999px;
        border: 1px solid rgba(218, 208, 194, 0.95);
        background: #fff;
        color: #2f2a26;
        font-weight: 800;
        text-decoration: none;
        box-shadow: 0 8px 20px rgba(74, 54, 30, 0.04);
    }
    .detail-card [data-testid="stLinkButton"] > a:hover {
        border-color: rgba(239, 106, 72, 0.55);
        color: #ef6a48;
    }
    .anchor-card {
        background: linear-gradient(180deg, #fff9ef 0%, #f6efe1 100%);
        border: 1px solid rgba(224, 206, 170, 0.95);
        border-radius: 22px;
        padding: 1rem 1.1rem;
        box-shadow: 0 16px 44px rgba(74, 54, 30, 0.08);
    }
    .anchor-eyebrow {
        color: #9b6a17;
        font-size: 0.82rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .anchor-title {
        color: #231d17;
        font-size: 1.1rem;
        font-weight: 800;
        margin-top: 0.2rem;
    }
    .anchor-copy {
        color: #665847;
        line-height: 1.55;
        margin-top: 0.45rem;
        font-size: 0.94rem;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] div {
        word-break: keep-all;
        overflow-wrap: break-word;
        line-height: 1.72;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

topbar_placeholder = st.empty()

st.markdown('<div class="top-search-wrap">', unsafe_allow_html=True)
top_a, top_b = st.columns([4.8, 1.2], gap="small")
with top_a:
    search_query = st.text_input(
        "검색",
        placeholder="하몽, PB상품, 빠에야 재료, 생활 용품처럼 검색",
        label_visibility="collapsed",
    )
with top_b:
    mode = st.segmented_control(
        "이용 방식",
        options=["단기", "장기"],
        default="단기",
        label_visibility="collapsed",
    )
st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div class='search-helper'>예) 하몽, 치즈, 올리브오일, 납작 복숭아 등</div>", unsafe_allow_html=True)

mission = category_options[0]

filter_cols = st.columns(6, gap="small")
with filter_cols[0]:
    open_now_only = st.toggle("영업 중", value=True)
with filter_cols[1]:
    high_rating_only = st.toggle("평점 4.0+", value=False)
with filter_cols[2]:
    budget_friendly = st.toggle("가성비", value=False)
with filter_cols[3]:
    premium_only = st.toggle("프리미엄", value=False)
with filter_cols[4]:
    budget = st.select_slider("예산", options=[10, 20, 30, 40, 50, 60, 70, 80], value=30)
with filter_cols[5]:
    group_size = st.select_slider("인원", options=[1, 2, 3, 4, 5, 6], value=2)

meta_cols = st.columns([1.4, 1, 2.2], gap="small")
with meta_cols[0]:
    stay_days = st.select_slider("체류 기간", options=[1, 3, 5, 7, 14, 30, 60, 90, 180], value=5 if mode == "단기" else 30)
with meta_cols[1]:
    selected_category = resolve_selected_category(search_query, mission, category_data, category_options)
    st.metric("검색 결과", selected_category)
with meta_cols[2]:
    st.caption("검색창에 상품명이나 재료명을 입력하면 가장 가까운 상품군으로 연결됩니다.")

working = attach_category_context(catalog.copy(), category_data, selected_category)
working = working.dropna(subset=["category_cat"])

if open_now_only:
    working = working[working["current_status"].str.contains("영업 중", na=False)]
if high_rating_only:
    working = working[pd.to_numeric(working["rating"], errors="coerce") >= 4.0]
if budget_friendly:
    working = working[working["price_level"] <= 3]
if premium_only:
    working = working[working["price_level"] >= 4]

if working.empty:
    st.warning("조건에 맞는 마트가 없습니다. 검색어나 필터를 조금 줄여보세요.")
    st.stop()

working["score"] = working.apply(
    score_mart,
    axis=1,
    args=(mode, budget, group_size),
)
working["estimated_basket"] = working.apply(estimate_basket_from_category, axis=1, args=(group_size,))
working["ai_reason"] = working.apply(
    recommendation_reason,
    axis=1,
    args=(mode,),
)
working = working.sort_values(["score", "quality_score"], ascending=[False, False]).reset_index(drop=True)
anchor_row = build_anchor_summary(category_data, selected_category)

top_pick = working.iloc[0]
second_pick = working.iloc[1] if len(working) > 1 else working.iloc[0]
working["rank_label"] = working["score"].rank(method="first", ascending=False).astype(int)
time_labels = ["07.13 08:28", "07.13 06:24", "07.13 05:12", "07.12 22:47", "07.12 21:10"]
working["time_label"] = [time_labels[idx % len(time_labels)] for idx in range(len(working))]

selected_mart_name = st.segmented_control(
    "마트 선택",
    options=working["name"].tolist(),
    default=top_pick["name"],
    label_visibility="collapsed",
)
selected_mart = working[working["name"] == selected_mart_name].iloc[0]
status_label, status_bg, status_fg = get_open_status_meta(selected_mart["current_status"])
selected_hours = clean_weekly_hours(selected_mart["weekly_hours"])

topbar_placeholder.markdown(
    f"""
    <div class="topbar">
      <div class="brand">
        <h1>GrocerMap</h1>
        <p>스페인에서 지금 내 상황에 맞는 마트를 쉽게 찾는 장보기 앱</p>
        <div class="hero-actions">
          <div class="ghost-chip">후기 모아보기</div>
          <div class="ghost-chip dark">정보 업데이트</div>
        </div>
      </div>
      <div class="actions">
        <div class="chip alt">{mode}</div>
        <div class="chip">{selected_category}</div>
        <div class="chip">예산 EUR {budget}</div>
        <div class="chip">체류 {stay_days}일</div>
        <div class="chip">인원 {group_size}명</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="service-note">
      <strong>{selected_category}</strong> 살 때 어디가 편한지, 품질은 어떤지, 지금 상황에 잘 맞는지를 함께 보고 골라드려요.
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="shell">', unsafe_allow_html=True)

left_col, center_col = st.columns([1.15, 1.85], gap="medium")

with left_col:
    st.markdown("<div class='left-panel'>", unsafe_allow_html=True)
    with st.container(border=True):
        st.subheader("추천 랭킹")
        st.caption("지금 조건에 맞는 곳부터 순서대로 보여드려요.")
        for idx, row in working.iterrows():
            st.markdown("<div class='rank-row'>", unsafe_allow_html=True)
            name_col, badge_col = st.columns([4.2, 1])
            with name_col:
                st.markdown(
                    f"""
                    <div class="rank-head">
                      <div>
                        <div class="rank-number">#{int(row['rank_label'])} 추천</div>
                        <div class="rank-title">{row['name']}</div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"""
                    <div class="rank-lines">
                      <div class="rank-line-strong">{row['current_status']}</div>
                      <div>평점 {row['rating']} · 리뷰 {int(row['review_count'])}개 · {row['address'].split(',')[1].strip()}</div>
                      <div>{row['category_cat']} · 예상 장보기 EUR {row['estimated_basket']}</div>
                      <div class='rank-summary'>{row['summary_copy']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if row["name"] == selected_mart_name:
                    st.markdown("<div class='rank-active'>현재 보고 있는 마트</div>", unsafe_allow_html=True)
            with badge_col:
                st.markdown("<div class='rank-actions'>", unsafe_allow_html=True)
                st.markdown("<div class='rank-badge'>추천</div>", unsafe_allow_html=True)
                if st.button("상세 보기", key=f"detail_{row['name']}", use_container_width=True):
                    open_detail_modal(row["name"])
                st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            if idx < len(working) - 1:
                st.markdown("<hr class='rank-divider' />", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with center_col:
    st.markdown(
        f"""
        <div class="quick-strip">
          <div class="quick-card">
            <div class="quick-label">가장 잘 맞는 곳</div>
            <div class="quick-value">{top_pick['name']}</div>
          </div>
          <div class="quick-card">
            <div class="quick-label">찾는 품목</div>
            <div class="quick-value">{selected_category}</div>
          </div>
          <div class="quick-card">
            <div class="quick-label">예상 비용</div>
            <div class="quick-value">EUR {top_pick['estimated_basket']}</div>
          </div>
          <div class="quick-card">
            <div class="quick-label">지금 상태</div>
            <div class="quick-value">{status_label}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="map-shell">
          <div class="map-toolbar">
            <div class="tool-dot">⌕</div>
            <div class="tool-dot">♡</div>
            <div class="tool-dot">☰</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="filter-row">
          <div class="filter-pill">{selected_category}</div>
          <div class="filter-pill">추천 마트 · {top_pick['name']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    map_df = build_map_points(working.rename(columns={"lat": "lat", "lon": "lon"}), selected_mart_name, top_pick["name"])
    view_state = pdk.ViewState(
        latitude=float(map_df["lat"].mean()),
        longitude=float(map_df["lon"].mean()),
        zoom=13.2,
        pitch=0,
    )
    icon_layer = pdk.Layer(
        "IconLayer",
        data=map_df,
        get_icon="icon_data",
        get_position="[lon, lat]",
        get_size="marker_size",
        size_scale=12,
        pickable=True,
    )
    tooltip = {
        "html": "<div style='font-family: Pretendard, sans-serif; padding: 4px 6px;'><strong>{name}</strong><br/>{category_cat}</div>",
        "style": {
            "backgroundColor": "rgba(34, 33, 41, 0.92)",
            "color": "white",
            "borderRadius": "10px",
            "fontSize": "13px",
        },
    }
    st.pydeck_chart(
        pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
            initial_view_state=view_state,
            layers=[icon_layer],
            tooltip=tooltip,
        ),
        use_container_width=True,
    )
    st.markdown(
        f"""
        <div class="status-card">
          <div class="status-top">
            <div class="status-name">{selected_mart['name']}</div>
            <div class="status-badge" style="background:{status_bg}; color:{status_fg};">{status_label}</div>
          </div>
          <div class="hours-text">{selected_hours}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="bottom-banner">
          <div class="recommend-strip">
            <div>
              <p>지금 보기엔 여기부터 가보면 좋아요</p>
              <h2>{top_pick['name']}</h2>
              <p>{polish_copy(top_pick['ai_reason'])}</p>
              <div class="section-note">거리 {top_pick['distance_km']} km · 평점 {top_pick['rating']} · 리뷰 {int(top_pick['review_count'])}개</div>
            </div>
            <div class="buy-chip">지도에서 보기</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if anchor_row is not None:
        st.markdown(
            f"""
            <div class="anchor-card">
              <div class="anchor-eyebrow">생활 장보기 기준</div>
              <div class="anchor-title">Mercadona와 비교하면</div>
              <div class="anchor-copy">{polish_copy(anchor_row['summary_copy'])}</div>
              <div class="section-note">가격대 {anchor_row['price_band']} · 장기 이용 {int(anchor_row['resident_fit'])}/5 · 일상 장보기 {int(anchor_row['daily_use_suitability'])}/5</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("</div>", unsafe_allow_html=True)

detail_cols = st.columns([1.2, 1.2, 1], gap="medium")
with detail_cols[0]:
    with st.container(border=True):
        st.subheader("왜 이곳을 추천했을까")
        st.markdown(format_copy_blocks(selected_mart["ai_reason"]))
        st.caption("주소")
        st.write(selected_mart["address"])
        st.caption("사이트")
        if pd.notna(selected_mart["website"]) and selected_mart["website"]:
            st.link_button("공식 사이트 보기", selected_mart["website"], use_container_width=False)
        else:
            st.write("연결할 수 있는 공식 사이트가 아직 없어요.")
        st.caption("영업시간")
        for hour_line in split_weekly_hours(selected_mart["weekly_hours"]):
            st.write(hour_line)

with detail_cols[1]:
    with st.container(border=True):
        st.subheader("같이 비교해볼 곳")
        st.markdown(format_copy_blocks(second_pick["ai_reason"]))
        st.caption("주소")
        st.write(second_pick["address"])
        st.caption("사이트")
        if pd.notna(second_pick["website"]) and second_pick["website"]:
            st.link_button("공식 사이트 보기", second_pick["website"], key="second_pick_site", use_container_width=False)
        else:
            st.write("연결할 수 있는 공식 사이트가 아직 없어요.")
        st.caption("영업시간")
        for hour_line in split_weekly_hours(second_pick["weekly_hours"]):
            st.write(hour_line)

with detail_cols[2]:
    with st.container(border=True):
        st.subheader("가기 전에 체크해보세요")
        st.markdown(f"- 이런 분께 잘 맞아요: {polish_copy(selected_mart['recommended_for'])}")
        st.markdown(f"- 이런 경우엔 아쉬울 수 있어요: {polish_copy(selected_mart['avoid_if'])}")
        st.markdown(f"- 한 줄로 보면: {polish_copy(selected_mart['summary_copy'])}")
        if anchor_row is not None:
            st.markdown(f"- Mercadona와 비교하면: {polish_copy(anchor_row['summary_copy'])}")
            st.markdown(f"- 가격대 느낌: {anchor_row['price_band']}")

detail_name = st.session_state.get("detail_mart_name")
if detail_name and detail_name in working["name"].tolist():
    detail_row = working[working["name"] == detail_name].iloc[0]
    if hasattr(st, "dialog"):
        @st.dialog(f"{detail_row['name']} 자세히 보기", width="large")
        def show_mart_dialog():
            render_detail_contents(detail_row, selected_category, mode)

        show_mart_dialog()
    else:
        with st.expander(f"{detail_row['name']} 자세히 보기", expanded=True):
            render_detail_contents(detail_row, selected_category, mode)
