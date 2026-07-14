# AI Grocery Discovery Platform Demo

Streamlit 기반 예시 UI입니다.

## 실행

```bash
cd "/Users/elena/Documents/스페인 캡스톤"
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py
```

## 포함 내용

- 마드리드 대표 마트 4곳 샘플 데이터
- Explorer / Resident 모드 전환
- 예산, 인원, 필요 상품 기반 추천 예시
- 지도형 UI와 마트 비교 테이블

## Google Places API 수집

마드리드 마트 기본 장소 정보를 바로 추출하려면 아래 스크립트를 실행하면 됩니다.

```bash
cd "/Users/elena/Documents/스페인 캡스톤"
export GOOGLE_MAPS_API_KEY="YOUR_API_KEY"
python3 google_places_madrid_extract.py \
  --query-file madrid_queries.txt \
  --nearby-points-json madrid_nearby_points.json \
  --output-csv outputs/madrid_grocery_places.csv \
  --output-json outputs/madrid_grocery_places.json
```

출력 필드:

- 장소명
- 주소
- 위도/경도
- Google Place ID
- 업종/카테고리
- 평점
- 리뷰 수
- 영업시간
- 전화번호
- 웹사이트
- 가격 수준
- 현재 영업 여부
- 일부 리뷰
- 일부 사진 메타데이터
