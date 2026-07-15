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
FOCUSED_PRODUCT_PATH = Path(__file__).resolve().parent / "outputs" / "focused_product_list_3categories.csv"
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


def load_focused_product_data() -> pd.DataFrame:
    return pd.read_csv(FOCUSED_PRODUCT_PATH)


def get_category_options(category_df: pd.DataFrame) -> list[str]:
    return category_df["category"].dropna().drop_duplicates().tolist()


def get_supported_search_options() -> list[str]:
    return ["하몽", "치즈", "올리브오일"]


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


def render_star_rating(score: int) -> str:
    filled = "★" * max(0, min(int(score), 5))
    empty = "☆" * max(0, 5 - min(int(score), 5))
    return f"{filled}{empty}"


def build_discount_note(mart_name: str, category: str) -> str:
    notes = {
        "El Corte Inglés Serrano": f"{category} 할인 정보는 아직 많지 않아요. 대신 시즌 기프트 세트나 묶음 구성이 올라오는 편이에요.",
        "Mercado de la Paz": f"{category}는 정가 할인보다는 당일 컨디션이나 점포별 구성이 더 크게 느껴지는 편이에요.",
        "Sánchez Romero": f"{category} 할인은 자주 보이진 않지만, 프리미엄 수입 식재료 행사 제보가 들어오면 바로 반영할 수 있어요.",
        "Mercadona": f"{category}는 큰 폭의 행사보다 일상 가격이 안정적인 편이에요. 생활형 장보기 기준으로 비교하기 좋아요.",
        "Carrefour Express": f"{category}는 시간대별 프로모션이나 간편식 묶음 제보가 들어오면 빠르게 반영하기 좋아요.",
    }
    return notes.get(mart_name, f"{category} 할인 정보가 들어오면 이곳에서 바로 확인할 수 있어요.")


def format_price_label(price: float, price_type: str, price_note: str) -> str:
    return f"가격 EUR {float(price):.2f}"


def format_price_caption(price_type: str, price_note: str) -> str:
    base = str(price_note or "").strip()
    if price_type == "exact_catalog":
        return f"{base} · 실제 카탈로그 기준"
    if price_type == "proxy_catalog":
        return f"{base} · 체인 카탈로그 기준"
    if price_type == "article_mentioned":
        return f"{base} · 기사 언급 기준"
    return f"{base} · 매장 성격 기반 추정"


def build_sample_reviews(mart_name: str, category: str, mode: str) -> list[dict]:
    mart_reviews = {
        "El Corte Inglés Serrano": [
            {"author": "seoyeon", "rating": 4, "availability": "판매 중 봤어요", "text": f"{category}를 선물용으로 고르기 편했고 매장이 정돈돼 있어서 초행자도 부담이 적었어요."},
            {"author": "mina", "rating": 5, "availability": "판매 중 봤어요", "text": "관광객 입장에서 브랜드를 비교하기 쉬웠고, 기념품처럼 사가기 좋은 느낌이 있었어요."},
            {"author": "jiyoon", "rating": 4, "availability": "판매 중 봤어요", "text": "급하게 들렀는데도 동선이 편해서 필요한 품목을 빠르게 찾을 수 있었어요."},
        ],
        "Mercado de la Paz": [
            {"author": "eunchae", "rating": 5, "availability": "판매 중 봤어요", "text": f"{category}를 사러 갔는데 일반 마트보다 시장 느낌이 강해서 구경하는 재미가 컸어요."},
            {"author": "soyoung", "rating": 4, "availability": "판매 중 봤어요", "text": "생활용품 장보기보다는 신선식품이나 하몽, 치즈 같은 재료를 사러 갈 때 더 잘 맞는 곳 같아요."},
            {"author": "jiwon", "rating": 4, "availability": "판매 중 봤어요", "text": "관광객 입장에서는 현지 장보기 경험이 살아 있어서 기억에 남는 매장이었어요."},
        ],
        "Sánchez Romero": [
            {"author": "chaewon", "rating": 4, "availability": "판매 중 봤어요", "text": f"{category} 코너가 깔끔하게 정리돼 있어서 비교해 보기 좋았어요."},
            {"author": "hyerin", "rating": 5, "availability": "판매 중 봤어요", "text": "가격은 가볍지 않지만 치즈, 하몽, 와인처럼 프리미엄 식재료를 볼 때 만족도가 높았어요."},
            {"author": "yuna", "rating": 4, "availability": "판매 중 봤어요", "text": "시장처럼 활기찬 느낌보다는 조용하고 정돈된 슈퍼마켓을 선호하면 잘 맞아요."},
        ],
        "Mercadona": [
            {"author": "areum", "rating": 4, "availability": "판매 중 봤어요", "text": f"{category}를 생활형 장보기 기준으로 보기 좋았고, 가격 감각을 잡기 쉬웠어요."},
            {"author": "minseo", "rating": 5, "availability": "판매 중 봤어요", "text": "유학생이나 장기 체류자라면 반복 구매 품목을 고르기에 가장 무난한 마트 같아요."},
            {"author": "dahye", "rating": 4, "availability": "판매 중 봤어요", "text": "화려하진 않지만 일상 장보기에 필요한 것들을 안정적으로 채우기 좋았어요."},
        ],
        "Carrefour Express": [
            {"author": "nayeon", "rating": 4, "availability": "판매 중 봤어요", "text": f"{category}가 급하게 필요할 때 늦은 시간에도 들를 수 있어서 편했어요."},
            {"author": "sejin", "rating": 4, "availability": "판매 중 봤어요", "text": "냉동식품이나 즉석식품, 생활용품처럼 바로 필요한 품목을 보충할 때 특히 유용했어요."},
            {"author": "haeun", "rating": 3, "availability": "판매 중 봤어요", "text": "프리미엄 장보기보다는 빠르고 실용적인 장보기에 더 잘 맞는 매장이에요."},
        ],
    }
    reviews = mart_reviews.get(mart_name, []).copy()
    if mode == "장기":
        reviews.append({"author": "soyeon", "rating": 4, "availability": "판매 중 봤어요", "text": "오래 머물 때는 자주 들르게 되는데, 동선이 편한지가 꽤 크게 느껴졌어요."})
    else:
        reviews.append({"author": "jiyu", "rating": 4, "availability": "판매 중 봤어요", "text": "짧게 머무는 일정에서는 분위기랑 접근성이 생각보다 크게 느껴졌어요."})
    return reviews[:3]


def build_product_sample_reviews(mart_name: str, category: str, product_name: str) -> list[dict]:
    lowered = product_name.lower()
    reviewer_pool = [
        "seohyun",
        "yeji",
        "minji",
        "jiae",
        "sua",
        "yebin",
        "gyuri",
        "somin",
        "chaerin",
        "hyerin",
        "jiwoo",
        "dabin",
        "nayoung",
        "sohee",
        "yerin",
        "haeun",
        "minseo",
        "jiyeon",
        "areum",
        "sejin",
    ]

    base_seed = sum(ord(char) for char in f"{mart_name}|{category}|{product_name}")

    def pick_reviewer(offset: int) -> str:
        return reviewer_pool[(base_seed + offset) % len(reviewer_pool)]

    def product_detail_lines() -> tuple[str, str]:
        if category == "하몽":
            if "bellota" in lowered and "100%" in lowered:
                return (
                    "기름기가 은은하게 퍼지고 향이 깊어서 한 입 먹었을 때 확실히 프리미엄 느낌이 있었어요.",
                    "가격대는 높지만 여행 중 한 번 제대로 사보고 싶은 하몽으로는 만족도가 높았어요.",
                )
            if "bellota" in lowered:
                return (
                    "풍미가 진하고 씹을수록 고소한 느낌이 살아 있어서 와인 안주로 잘 어울렸어요.",
                    "일반 하몽보다 존재감이 확실해서 특별한 날 먹기 좋았지만, 매일 꺼내 먹기엔 조금 묵직했어요.",
                )
            if "ibérico" in lowered or "iberico" in lowered:
                return (
                    "짠맛보다 감칠맛이 먼저 올라와서 빵이나 치즈랑 같이 두기 좋았어요.",
                    "풍미는 충분히 좋았지만 벨로타 급처럼 압도적인 차이가 나진 않았어요.",
                )
            if "serrano" in lowered:
                return (
                    "익숙하고 깔끔한 맛이라 처음 하몽을 사는 사람도 부담 없이 고르기 좋았어요.",
                    "대신 깊이감은 이베리코 계열보다 덜해서 비교하면 조금 담백하게 느껴졌어요.",
                )
            if "paleta" in lowered:
                return (
                    "결이 부드럽고 조금 더 가볍게 넘어가서 여러 명이 나눠 먹기 편했어요.",
                    "맛 차이를 세세하게 보는 사람이 아니라면 일반 jamón과 구분이 크게 안 갈 수도 있어요.",
                )
            return (
                "전체적으로 무난하게 먹기 좋았고 여행 중 간단히 사기에도 부담이 적었어요.",
                "다만 특별한 포인트를 기대하면 조금 평범하게 느껴질 수 있었어요.",
            )
        if category == "치즈":
            if "manchego" in lowered:
                return (
                    "스페인 대표 치즈답게 맛의 방향이 분명해서 처음 담아도 크게 실패할 느낌은 없었어요.",
                    "입문용으로는 좋지만 강하게 기억에 남는 개성을 찾는다면 조금 얌전하게 느껴질 수 있어요.",
                )
            if "idiaz" in lowered or "ahumado" in lowered:
                return (
                    "훈연향이 은근하게 올라와서 한 조각만 먹어도 존재감이 남는 치즈였어요.",
                    "향이 분명해서 취향은 갈릴 수 있고, 매일 먹기엔 살짝 진하게 느껴질 수 있어요.",
                )
            if "comté" in lowered or "comte" in lowered:
                return (
                    "버터 같은 고소한 느낌이 있어서 빵이랑 같이 먹으면 만족감이 확 올라갔어요.",
                    "맛은 좋았지만 일상용보다는 조금 기분 내고 싶을 때 어울리는 가격대였어요.",
                )
            if "oveja" in lowered:
                return (
                    "양젖 치즈 특유의 진한 맛이 살아 있어서 하몽이나 와인과 같이 두기 좋았어요.",
                    "존재감은 확실했지만 산뜻한 치즈를 기대하면 조금 무겁게 느껴질 수 있어요.",
                )
            if "cabra" in lowered:
                return (
                    "산뜻한 산미가 있어서 샐러드나 플래터에 올렸을 때 확실히 살아났어요.",
                    "염소치즈 특유의 향이 있어 처음 먹는 사람은 취향이 갈릴 수 있어요.",
                )
            if "truf" in lowered:
                return (
                    "트러플 향이 퍼져서 한 조각만 먹어도 꽤 고급스럽게 느껴졌어요.",
                    "개성은 확실하지만 자주 먹는 데일리 치즈로 두기엔 조금 진한 편이었어요.",
                )
            if "semicurado" in lowered:
                return (
                    "너무 세지 않고 부드럽게 넘어가서 집에서 자주 꺼내 먹기 좋았어요.",
                    "편하게 먹기엔 좋지만 특별히 기억에 남는 포인트는 약한 편이었어요.",
                )
            return (
                "전체적으로 먹기 편하고 여러 음식에 곁들이기 쉬운 타입이었어요.",
                "특별한 개성을 기대하면 조금 평범하게 느껴질 수도 있었어요.",
            )
        if category == "올리브오일":
            if "arbequina" in lowered:
                return (
                    "향이 부드럽고 끝맛이 깔끔해서 샐러드나 빵에 바로 쓰기 좋았어요.",
                    "강한 올리브 향을 기대했다면 생각보다 순하게 느껴질 수 있어요.",
                )
            if "picual" in lowered:
                return (
                    "끝맛이 또렷해서 토마토나 구운 채소에 뿌리면 존재감이 분명했어요.",
                    "향이 뚜렷한 편이라 순한 오일을 찾는 사람에겐 조금 세게 느껴질 수 있어요.",
                )
            if "hojiblanca" in lowered:
                return (
                    "균형감이 좋아서 집에서 두루 쓰기 편한 기본 오일 느낌이었어요.",
                    "확 튀는 캐릭터보다는 여러 요리에 무난하게 맞는 쪽에 가까웠어요.",
                )
            if "carbonell" in lowered or "coosur" in lowered:
                return (
                    "익숙한 브랜드라 처음 고를 때 심리적으로 편했고 실패 확률이 낮아 보였어요.",
                    "대신 현지에서만 사야 할 특별한 느낌은 조금 덜했어요.",
                )
            if "gran selección" in lowered or "gran seleccion" in lowered:
                return (
                    "일반 제품보다 향이 조금 더 또렷해서 요리 마무리용으로 쓰기 좋았어요.",
                    "가격이 올라가다 보니 막 쓰는 오일보다는 아껴 쓰게 되는 느낌이었어요.",
                )
            return (
                "일상적으로 자주 쓰기 좋고 요리용으로도 무난하게 활용할 수 있었어요.",
                "대신 풍미 차이를 크게 따지는 사람에겐 조금 평이하게 느껴질 수 있어요.",
            )
        return (
            f"{product_name}는 전반적으로 써보기 무난한 상품이었어요.",
            "아주 강한 개성보다는 기본에 충실한 느낌이었어요.",
        )

    mart_tone = {
        "El Corte Inglés Serrano": {
            "strength": "고르기 쉽고 선물용으로 보기 좋아요",
            "weakness": "일상 장보기 기준으로는 가격이 조금 높게 느껴져요",
            "rating": 4,
            "keywords": ["맛이 좋아요"],
        },
        "Mercado de la Paz": {
            "strength": "현지 시장에서 직접 고르는 느낌이 살아 있어요",
            "weakness": "한눈에 비교하기보다는 천천히 둘러봐야 해요",
            "rating": 5,
            "keywords": ["맛이 좋아요", "양이 많아요"],
        },
        "Sánchez Romero": {
            "strength": "정돈된 분위기에서 프리미엄 상품을 보기 좋아요",
            "weakness": "가성비보다는 품질 중심이라 가격 부담은 있어요",
            "rating": 4,
            "keywords": ["맛이 좋아요"],
        },
        "Mercadona": {
            "strength": "무난하게 집어 들기 좋고 생활형으로 쓰기 편해요",
            "weakness": "선물용이나 특별한 느낌은 조금 약해요",
            "rating": 4,
            "keywords": ["가격이 싸요"],
        },
        "Carrefour Express": {
            "strength": "급하게 필요할 때 바로 사기 편해요",
            "weakness": "선택지가 넓지 않아서 비교해서 고르기엔 아쉬워요",
            "rating": 3,
            "keywords": ["가격이 싸요"],
        },
    }
    extra_variation = {
        "El Corte Inglés Serrano": [
            "포장이나 진열이 깔끔해서 처음 보는 제품도 덜 어렵게 느껴졌어요.",
            "브랜드 설명을 보면서 고를 수 있는 점은 좋았지만, 빠르게 담아 가는 느낌은 덜했어요.",
        ],
        "Mercado de la Paz": [
            "매대마다 보는 재미는 있었지만, 생활용품까지 한 번에 해결하는 동선은 아니었어요.",
            "현지 느낌은 가장 강했지만, 급하게 사고 나와야 할 때는 조금 번거롭게 느껴질 수 있어요.",
        ],
        "Sánchez Romero": [
            "조용하고 정돈된 분위기라 천천히 보기 좋았지만, 실속형 쇼핑을 기대하면 아쉬울 수 있어요.",
            "제품 퀄리티는 좋았는데, 한 번에 여러 개 담기엔 부담이 생길 수 있어요.",
        ],
        "Mercadona": [
            "반복 구매용으로는 괜찮았지만, 맛에서 큰 차별점이 느껴지는 타입은 아니었어요.",
            "가격 감각 잡기엔 편했지만 프리미엄 느낌을 기대하면 조금 평범하게 느껴질 수 있어요.",
        ],
        "Carrefour Express": [
            "늦은 시간에도 살 수 있는 건 좋았지만, 선택 폭은 확실히 제한적이었어요.",
            "바로 사 오기엔 편했는데, 상품을 비교하는 재미는 적은 편이었어요.",
        ],
    }

    tone = mart_tone.get(mart_name, mart_tone["Mercadona"])
    detail_lines = product_detail_lines()
    extra_lines = extra_variation.get(mart_name, ["전체적으로 무난했지만, 아주 강한 인상을 남기는 타입은 아니었어요."])

    review_one = {
        "author": pick_reviewer(1),
        "rating": tone["rating"],
        "availability": "판매 중 봤어요",
        "keywords": tone["keywords"],
        "text": f"{detail_lines[0]} {tone['strength']}. 다만 {tone['weakness']}.",
    }
    review_two = {
        "author": pick_reviewer(7),
        "rating": max(3, tone["rating"] - 1 if mart_name in {"Mercadona", "Carrefour Express"} else tone["rating"]),
        "availability": "판매 중 봤어요",
        "keywords": ["양이 많아요"] if category != "올리브오일" else ["가격이 싸요"],
        "text": f"{detail_lines[min(1, len(detail_lines) - 1)]} {extra_lines[0]}",
    }
    if "100%" in lowered or "bellota" in lowered:
        review_one["author"] = pick_reviewer(3)
        review_one["rating"] = min(5, tone["rating"] + 1)
        review_one["keywords"] = ["맛이 좋아요"]
        review_one["text"] = f"{product_name}는 한 입 먹었을 때 향과 지방감이 확실히 살아 있었어요. {tone['strength']}. 대신 {tone['weakness']}."
    if "gran selección" in lowered or "gran seleccion" in lowered:
        review_two["author"] = pick_reviewer(9)
        review_two["text"] = f"{product_name}는 요리 마무리용으로 뿌렸을 때 차이가 느껴졌어요. {extra_lines[1]}"
    if "cabra" in lowered:
        review_two["author"] = pick_reviewer(11)
        review_two["keywords"] = ["맛이 좋아요"]
        review_two["text"] = f"{product_name}는 샐러드나 플래터에 올렸을 때 향이 확 살아났어요. {extra_lines[0]}"
    if "picual" in lowered or "arbequina" in lowered:
        review_two["author"] = pick_reviewer(13)
        review_two["keywords"] = ["맛이 좋아요"]
        review_two["text"] = f"{product_name}는 품종 차이를 비교해 보고 싶은 사람에겐 재미가 있었어요. {extra_lines[1]}"
    if "serrano" in lowered:
        review_two["author"] = pick_reviewer(15)
        review_two["keywords"] = ["가격이 싸요"]
        review_two["text"] = f"{product_name}는 부담 없이 담기 좋았고 샌드위치나 간단한 안주용으로 쓰기 편했어요. {extra_lines[1]}"
    if "manchego" in lowered:
        review_two["author"] = pick_reviewer(17)
        review_two["keywords"] = ["맛이 좋아요"]
        review_two["text"] = f"{product_name}는 처음 스페인 치즈를 살 때 가장 안전한 선택처럼 느껴졌어요. {extra_lines[1]}"
    if "truf" in lowered:
        review_two["author"] = pick_reviewer(19)
        review_two["keywords"] = ["맛이 좋아요"]
        review_two["text"] = f"{product_name}는 향이 강해서 와인 안주로는 좋았지만 한 번에 많이 먹기엔 진했어요. {extra_lines[0]}"
    if "carbonell" in lowered or "coosur" in lowered:
        review_two["author"] = pick_reviewer(5)
        review_two["keywords"] = ["가격이 싸요"]
        review_two["text"] = f"{product_name}는 요리에 편하게 쓰기 좋았고 브랜드가 익숙해서 장바구니에 담기 쉬웠어요. {extra_lines[0]}"

    return [review_one, review_two]


def build_recipe_tip(category: str, product_name: str) -> dict:
    recipe_map = {
        "하몽": {
            "title": "추천 레시피 · 판 콘 토마테",
            "ingredients": "토마토, 바게트, 올리브오일",
            "tip": f"{product_name}는 바게트 위에 토마토를 문지르고 올리브오일을 뿌린 뒤 올려 먹으면 간단한 한 끼나 와인 안주로 잘 어울려요.",
        },
        "치즈": {
            "title": "추천 레시피 · 치즈 플래터",
            "ingredients": "바게트, 포도나 복숭아, 견과류",
            "tip": f"{product_name}는 과일과 견과류를 곁들이면 바로 먹기 좋은 플래터가 되고, 남으면 샐러드 토핑으로도 활용하기 좋아요.",
        },
        "올리브오일": {
            "title": "추천 레시피 · 토마토 샐러드",
            "ingredients": "토마토, 소금, 후추, 빵 또는 모차렐라",
            "tip": f"{product_name}는 토마토 위에 바로 뿌려 간단한 샐러드로 먹기 좋고, 파스타나 구운 채소 마무리용으로 써도 풍미가 잘 살아나요.",
        },
    }
    return recipe_map.get(
        category,
        {
            "title": "추천 레시피",
            "ingredients": "집에 있는 간단한 재료",
            "tip": f"{product_name}는 집에서 가볍게 곁들이기 좋은 재료예요.",
        },
    )


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
    st.caption("직접 가본 경험을 바탕으로 남긴 후기예요. 판매 여부와 만족도를 함께 볼 수 있어요.")
    for review in build_sample_reviews(row["name"], selected_category, mode):
        st.markdown(
            f"**{review['author']}** · {render_star_rating(review['rating'])} · {review['availability']}\n\n{review['text']}"
        )

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
focused_product_data = load_focused_product_data()
category_options = get_supported_search_options()

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
    .product-panel {
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 0.15rem 0 0.4rem 0;
        box-shadow: none;
        height: 100%;
    }
    .product-section {
        padding: 0.35rem 0 0.95rem 0;
    }
    .product-section + .product-section {
        border-top: 1px solid #ebe3d8;
        margin-top: 0.2rem;
        padding-top: 1rem;
    }
    .product-mart {
        color: #201b17;
        font-size: 1rem;
        font-weight: 800;
        margin-bottom: 0.1rem;
    }
    .product-meta {
        color: #8b7760;
        font-size: 0.83rem;
        margin-bottom: 0.55rem;
    }
    .product-item {
        background: #fbfaf7;
        border: 1px solid rgba(231, 223, 212, 0.92);
        border-radius: 16px;
        padding: 0.7rem 0.8rem;
        margin-bottom: 0.5rem;
    }
    .product-name {
        color: #221d18;
        font-size: 0.94rem;
        font-weight: 700;
        line-height: 1.45;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .product-price {
        color: #ef6a48;
        font-size: 0.9rem;
        font-weight: 800;
        margin-top: 0.18rem;
    }
    .product-note {
        color: #8b7760;
        font-size: 0.78rem;
        margin-top: 0.14rem;
        line-height: 1.45;
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
        placeholder="하몽, 치즈, 올리브오일처럼 검색",
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
st.markdown("<div class='search-helper'>예) 하몽, 치즈, 올리브오일</div>", unsafe_allow_html=True)

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

product_panel_df = focused_product_data[focused_product_data["category_ko"] == selected_category].copy()
product_panel_df["mart_name"] = pd.Categorical(
    product_panel_df["mart_name"],
    categories=working["name"].tolist(),
    ordered=True,
)
product_panel_df = product_panel_df.sort_values(["mart_name", "price_eur"]).reset_index(drop=True)

left_col, center_col, right_col = st.columns([1.05, 1.45, 1.05], gap="medium")

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

with right_col:
    st.markdown("<div class='product-panel'>", unsafe_allow_html=True)
    st.subheader("상품 리스트")
    st.caption(f"{selected_category} 검색 시 마트별로 먼저 볼 만한 대표 상품이에요.")
    if product_panel_df.empty:
        st.info("이 품목은 아직 상품 리스트가 준비되지 않았어요.")
    else:
        for mart_name in working["name"].tolist():
            mart_products = product_panel_df[product_panel_df["mart_name"] == mart_name]
            if mart_products.empty:
                continue
            mart_meta = working[working["name"] == mart_name].iloc[0]
            st.markdown(
                f"""
                <div class="product-section">
                  <div class="product-mart">{mart_name}</div>
                  <div class="product-meta">평점 {mart_meta['rating']} · {mart_meta['address'].split(',')[1].strip()}</div>
                """,
                unsafe_allow_html=True,
            )
            for _, item in mart_products.iterrows():
                product_key = f"{mart_name}_{item['product_name_display']}".replace(" ", "_").replace("/", "_")
                st.markdown(
                    f"""
                    <div class="product-item">
                      <div class="product-name">{item['product_name_display']}</div>
                      <div class="product-price">{format_price_label(item['price_eur'], item['price_type'], item['price_note'])}</div>
                      <div class="product-note">{format_price_caption(item['price_type'], item['price_note'])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                with st.expander("제품별 상세 리뷰", expanded=False):
                    st.caption("이 상품에 대한 실제 사용 후기를 모으는 영역이에요.")
                    for review in build_product_sample_reviews(mart_name, selected_category, item["product_name_display"]):
                        keywords = " · ".join(review["keywords"])
                        st.markdown(
                            f"**{review['author']}** · {render_star_rating(review['rating'])} · {review['availability']}\n\n`{keywords}`\n\n{review['text']}"
                        )
                    if mode == "장기":
                        recipe_tip = build_recipe_tip(selected_category, item["product_name_display"])
                        st.info(
                            f"**{recipe_tip['title']}**\n\n"
                            f"같이 준비하면 좋아요: {recipe_tip['ingredients']}\n\n"
                            f"{recipe_tip['tip']}"
                        )

                    sale_status = st.selectbox(
                        "판매 여부",
                        options=["판매 중 봤어요", "품절이었어요", "못 봤어요"],
                        key=f"prod_status_{product_key}",
                    )
                    satisfaction = st.radio(
                        "상품 만족도",
                        options=[1, 2, 3, 4, 5],
                        index=3,
                        key=f"prod_rating_{product_key}",
                        format_func=lambda value: render_star_rating(value),
                        horizontal=True,
                    )
                    selected_keywords = st.multiselect(
                        "키워드 선택",
                        options=["가격이 싸요", "맛이 좋아요", "양이 많아요"],
                        key=f"prod_keywords_{product_key}",
                        placeholder="리뷰에 맞는 키워드를 골라주세요.",
                    )
                    review_text = st.text_area(
                        "한 줄 후기",
                        key=f"prod_text_{product_key}",
                        height=90,
                        placeholder=f"{item['product_name_display']} 먹어본 느낌이나 가성비, 양에 대한 인상을 적어주세요.",
                    )
                    selected_keyword_text = " · ".join(selected_keywords) if selected_keywords else "선택한 키워드 없음"
                    st.caption(
                        f"선택한 판매 여부: {sale_status} · 만족도: {render_star_rating(satisfaction)} · 키워드: {selected_keyword_text}"
                    )
                    if st.button("리뷰 작성 예시 보기", key=f"prod_preview_{product_key}"):
                        preview_text = review_text.strip() or f"{item['product_name_display']}는 생각보다 고르기 쉬웠고 전체적으로 만족스러웠어요."
                        st.success("이런 형식으로 제품별 리뷰가 쌓이면 추천 품질이 더 좋아져요.")
                        st.markdown(
                            f"**{item['product_name_display']} 리뷰 예시**\n\n- 판매 여부: {sale_status}\n- 만족도: {render_star_rating(satisfaction)}\n- 키워드: {selected_keyword_text}\n- 후기: {preview_text}"
                        )
            st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

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
