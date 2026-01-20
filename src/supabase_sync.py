"""Supabase 동기화 모듈 (v2)

문제와 해설을 하나의 레코드로 통합하여 저장
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class UploadResult:
    """업로드 결과"""
    success: bool
    textbook_id: Optional[str] = None
    question_count: int = 0
    error_message: Optional[str] = None


@dataclass
class SimilarQuestion:
    """유사 문제 검색 결과"""
    id: str
    question_number: Optional[str]
    question_text: str
    answer: Optional[str]
    solution_text: Optional[str]
    textbook_id: str
    textbook_title: str
    theme_id: Optional[str]
    theme_name: Optional[str]
    similarity: float


class SupabaseSync:
    """Supabase 동기화 클래스"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        """Supabase 클라이언트 (lazy loading)"""
        if self._client is None:
            from .supabase_client import get_supabase_client
            self._client = get_supabase_client()
        return self._client

    def is_connected(self) -> bool:
        """연결 상태 확인"""
        return self.client is not None

    def upload_textbook(
        self,
        title: str,
        themes: List[Dict[str, Any]],
        questions: List[Dict[str, Any]],
        subtitle: Optional[str] = None,
        publisher: Optional[str] = None,
        year: Optional[int] = None,
        subject: Optional[str] = None,
        source_pdf: Optional[str] = None
    ) -> UploadResult:
        """교재 전체 업로드

        Args:
            title: 교재 제목
            themes: 테마 리스트 [{name, color}, ...]
            questions: 문제 리스트 (문제와 해설이 페어링됨)
                각 항목: {
                    "ai_result": {...},  # 문제 AI 분석 결과
                    "solution_ai_result": {...},  # 해설 AI 분석 결과 (선택)
                    "theme_name": "...",
                    "page": 페이지번호,
                    "x1", "y1", "x2", "y2": bbox,
                    "solution_page": 해설페이지 (선택),
                    "solution_x1", "solution_y1", "solution_x2", "solution_y2": 해설bbox (선택)
                }
            subtitle: 부제목
            publisher: 출판사
            year: 출판연도
            subject: 교과목
            source_pdf: 원본 PDF 파일명

        Returns:
            UploadResult
        """
        if not self.client:
            return UploadResult(False, error_message="Supabase 연결이 설정되지 않았습니다.")

        try:
            # 1. 교재 생성
            textbook_data = {
                "title": title,
                "subtitle": subtitle,
                "publisher": publisher,
                "year": year,
                "subject": subject,
                "source_pdf": source_pdf,
                "total_pages": len(set(q.get("page", 1) for q in questions))
            }

            textbook_result = self.client.table("textbooks").insert(textbook_data).execute()
            textbook_id = textbook_result.data[0]["id"]

            # 2. 테마 생성 (이름 → ID 매핑)
            theme_id_map = {}
            for i, theme in enumerate(themes):
                if theme.get("deleted"):
                    continue

                theme_data = {
                    "textbook_id": textbook_id,
                    "name": theme["name"],
                    "color": theme.get("color", "#3498db"),
                    "sort_order": i
                }

                result = self.client.table("themes").insert(theme_data).execute()
                theme_id_map[theme["name"]] = result.data[0]["id"]

            # 3. 문제 업로드 (문제 + 해설 통합)
            from .embedding import create_embedding

            question_count = 0
            for q in questions:
                ai_result = q.get("ai_result", {})
                if not ai_result:
                    continue

                content = ai_result.get("content", {})
                question_text = content.get("question_text", "")

                # 해설 정보
                solution_ai_result = q.get("solution_ai_result", {})
                solution_content = solution_ai_result.get("content", {}) if solution_ai_result else {}
                solution_text = solution_content.get("solution_text") or solution_content.get("question_text")

                # 임베딩 생성 (문제 텍스트 기준)
                embedding = create_embedding(question_text) if question_text else None

                # 테마 ID 조회
                theme_name = ai_result.get("theme_name") or q.get("theme_name")
                theme_id = theme_id_map.get(theme_name) if theme_name else None

                # 모델 정보
                model_info = ai_result.get("model", {})

                # 정답: 문제 분석 결과 또는 해설 분석 결과에서 가져옴
                answer = content.get("answer") or solution_content.get("answer")

                # 문제 데이터 (문제 + 해설 통합)
                question_data = {
                    "textbook_id": textbook_id,
                    "theme_id": theme_id,
                    "question_number": str(ai_result.get("question_number")) if ai_result.get("question_number") else None,
                    "question_text": question_text,
                    "answer": answer,
                    "solution_text": solution_text,
                    "ai_model_id": model_info.get("id"),
                    "ai_model_name": model_info.get("name"),
                    "ai_model_provider": model_info.get("provider"),
                    # 문제 위치
                    "source_page": q.get("page"),
                    "bbox_x1": q.get("x1"),
                    "bbox_y1": q.get("y1"),
                    "bbox_x2": q.get("x2"),
                    "bbox_y2": q.get("y2"),
                    # 해설 위치
                    "solution_page": q.get("solution_page"),
                    "solution_bbox_x1": q.get("solution_x1"),
                    "solution_bbox_y1": q.get("solution_y1"),
                    "solution_bbox_x2": q.get("solution_x2"),
                    "solution_bbox_y2": q.get("solution_y2"),
                    "embedding": embedding
                }

                result = self.client.table("questions").insert(question_data).execute()
                question_id = result.data[0]["id"]

                # 선택지 업로드 (문제용)
                choices = content.get("choices", [])
                for i, choice in enumerate(choices):
                    choice_data = {
                        "question_id": question_id,
                        "label": choice.get("label", ""),
                        "text": choice.get("text", ""),
                        "sort_order": i
                    }
                    self.client.table("question_choices").insert(choice_data).execute()

                # 보기 업로드 (문제용)
                sub_questions = content.get("sub_questions", [])
                for i, sub in enumerate(sub_questions):
                    sub_data = {
                        "question_id": question_id,
                        "label": sub.get("label", ""),
                        "text": sub.get("text", ""),
                        "sort_order": i
                    }
                    self.client.table("question_sub_items").insert(sub_data).execute()

                # 그래프/도형 업로드 (문제용)
                figures = content.get("figures", [])
                for i, figure in enumerate(figures):
                    bbox = figure.get("bbox_percent", {})
                    figure_data = {
                        "question_id": question_id,
                        "figure_type": figure.get("figure_type"),
                        "bbox_x1": bbox.get("x1"),
                        "bbox_y1": bbox.get("y1"),
                        "bbox_x2": bbox.get("x2"),
                        "bbox_y2": bbox.get("y2"),
                        "tikz_code": figure.get("tikz_code"),
                        "figure_data": figure.get("mathematical_analysis"),
                        "sort_order": i
                    }
                    self.client.table("question_figures").insert(figure_data).execute()

                # 그래프/도형 해석 업로드 (해설용)
                solution_figures = solution_content.get("figures", [])
                for i, figure in enumerate(solution_figures):
                    bbox = figure.get("bbox_percent", {})
                    figure_data = {
                        "question_id": question_id,
                        "figure_type": figure.get("figure_type"),
                        "bbox_x1": bbox.get("x1"),
                        "bbox_y1": bbox.get("y1"),
                        "bbox_x2": bbox.get("x2"),
                        "bbox_y2": bbox.get("y2"),
                        "tikz_code": figure.get("tikz_code"),
                        "figure_data": figure.get("mathematical_analysis"),
                        "sort_order": i
                    }
                    self.client.table("solution_figures").insert(figure_data).execute()

                # 핵심 개념 업로드
                key_concepts = content.get("key_concepts", [])
                for concept in key_concepts:
                    if concept:
                        concept_data = {
                            "question_id": question_id,
                            "concept_name": concept
                        }
                        self.client.table("key_concepts").insert(concept_data).execute()

                question_count += 1

            return UploadResult(
                success=True,
                textbook_id=textbook_id,
                question_count=question_count
            )

        except Exception as e:
            return UploadResult(False, error_message=str(e))

    def search_similar(
        self,
        question_text: str,
        threshold: float = 0.7,
        limit: int = 10,
        textbook_id: Optional[str] = None,
        theme_id: Optional[str] = None
    ) -> List[SimilarQuestion]:
        """유사 문제 검색

        Args:
            question_text: 검색할 문제 텍스트
            threshold: 유사도 임계값 (0~1)
            limit: 최대 결과 수
            textbook_id: 특정 교재로 필터링
            theme_id: 특정 테마로 필터링

        Returns:
            유사 문제 리스트
        """
        if not self.client:
            return []

        try:
            from .embedding import create_embedding

            # 검색어 임베딩 생성
            embedding = create_embedding(question_text)
            if not embedding:
                return []

            # RPC 호출로 유사 문제 검색
            result = self.client.rpc(
                "search_similar_questions",
                {
                    "query_embedding": embedding,
                    "match_threshold": threshold,
                    "match_count": limit,
                    "filter_textbook_id": textbook_id,
                    "filter_theme_id": theme_id
                }
            ).execute()

            # 결과 변환
            similar_questions = []
            for row in result.data:
                similar_questions.append(SimilarQuestion(
                    id=row["id"],
                    question_number=row.get("question_number"),
                    question_text=row.get("question_text", ""),
                    answer=row.get("answer"),
                    solution_text=row.get("solution_text"),
                    textbook_id=row.get("textbook_id", ""),
                    textbook_title=row.get("textbook_title", ""),
                    theme_id=row.get("theme_id"),
                    theme_name=row.get("theme_name"),
                    similarity=row.get("similarity", 0.0)
                ))

            return similar_questions

        except Exception as e:
            print(f"[ERROR] 유사 문제 검색 실패: {e}")
            return []

    def get_textbooks(self) -> List[Dict[str, Any]]:
        """교재 목록 조회"""
        if not self.client:
            return []

        try:
            result = self.client.table("textbooks").select("*").order("created_at", desc=True).execute()
            return result.data
        except Exception as e:
            print(f"[ERROR] 교재 목록 조회 실패: {e}")
            return []

    def get_themes(self, textbook_id: str) -> List[Dict[str, Any]]:
        """특정 교재의 테마 목록 조회"""
        if not self.client:
            return []

        try:
            result = self.client.table("themes").select("*").eq(
                "textbook_id", textbook_id
            ).eq(
                "deleted", False
            ).order("sort_order").execute()
            return result.data
        except Exception as e:
            print(f"[ERROR] 테마 목록 조회 실패: {e}")
            return []

    def get_questions(
        self,
        textbook_id: Optional[str] = None,
        theme_id: Optional[str] = None,
        question_number: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """문제 조회

        Args:
            textbook_id: 교재 ID로 필터링
            theme_id: 테마 ID로 필터링
            question_number: 문제 번호로 필터링

        Returns:
            문제 리스트 (해설 포함)
        """
        if not self.client:
            return []

        try:
            query = self.client.table("questions").select(
                "*, themes(name, color), textbooks(title)"
            )

            if textbook_id:
                query = query.eq("textbook_id", textbook_id)
            if theme_id:
                query = query.eq("theme_id", theme_id)
            if question_number:
                query = query.eq("question_number", question_number)

            result = query.order("question_number").execute()
            return result.data

        except Exception as e:
            print(f"[ERROR] 문제 조회 실패: {e}")
            return []


# 싱글톤 인스턴스
_sync_instance = None


def get_supabase_sync() -> SupabaseSync:
    """SupabaseSync 싱글톤 반환"""
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = SupabaseSync()
    return _sync_instance
