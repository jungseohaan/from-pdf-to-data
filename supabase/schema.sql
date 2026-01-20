-- ============================================================
-- Supabase 스키마: 수학 문제 데이터베이스 (v2)
-- ============================================================
-- 변경사항 (v2):
-- - 문제와 해설을 하나의 questions 레코드에 통합
-- - type, linked_question_id 필드 제거
-- - solution_text, solution_figures 필드 추가
-- ============================================================

-- pgvector 확장 활성화 (유사 문제 검색용)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. textbooks (교재)
-- ============================================================
CREATE TABLE IF NOT EXISTS textbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 기본 정보
    title TEXT NOT NULL,                    -- 교재명 (예: "2024 수능완성 수학영역")
    subtitle TEXT,                          -- 부제목 (예: "미적분")
    publisher TEXT,                         -- 출판사
    year INTEGER,                           -- 출판연도
    subject TEXT,                           -- 교과목 (예: "수학", "수학I", "미적분")

    -- 메타데이터
    source_pdf TEXT,                        -- 원본 PDF 파일명
    total_pages INTEGER,                    -- 총 페이지 수

    -- 타임스탬프
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_textbooks_title ON textbooks(title);
CREATE INDEX IF NOT EXISTS idx_textbooks_subject ON textbooks(subject);
CREATE INDEX IF NOT EXISTS idx_textbooks_year ON textbooks(year);

-- ============================================================
-- 2. themes (테마/단원)
-- ============================================================
CREATE TABLE IF NOT EXISTS themes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    textbook_id UUID NOT NULL REFERENCES textbooks(id) ON DELETE CASCADE,

    -- 기본 정보
    name TEXT NOT NULL,                     -- 테마/단원명 (예: "1. 수열의 극한")
    color TEXT DEFAULT '#3498db',           -- UI 표시 색상
    sort_order INTEGER DEFAULT 0,           -- 정렬 순서

    -- 상태
    deleted BOOLEAN DEFAULT FALSE,          -- 삭제 표시 (soft delete)

    -- 타임스탬프
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- 복합 유니크: 같은 교재 내 테마명 중복 방지
    UNIQUE(textbook_id, name)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_themes_textbook ON themes(textbook_id);
CREATE INDEX IF NOT EXISTS idx_themes_name ON themes(name);

-- ============================================================
-- 3. questions (문제 + 해설 통합)
-- ============================================================
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    textbook_id UUID NOT NULL REFERENCES textbooks(id) ON DELETE CASCADE,
    theme_id UUID REFERENCES themes(id) ON DELETE SET NULL,

    -- 문제 식별
    question_number TEXT,                   -- 문제 번호 (예: "1", "2-1", "가")

    -- === 문제 본문 ===
    question_text TEXT,                     -- 문제 본문 (LaTeX 포함)

    -- === 정답 및 해설 ===
    answer TEXT,                            -- 정답 (예: "①", "24", "ㄱ, ㄴ")
    solution_text TEXT,                     -- 해설 본문 (LaTeX 포함)

    -- AI 분석 메타데이터
    ai_model_id TEXT,                       -- 분석에 사용된 모델 ID
    ai_model_name TEXT,                     -- 모델 표시명
    ai_model_provider TEXT,                 -- 제공자 (gemini/openai)

    -- 원본 위치 정보 (문제)
    source_page INTEGER,                    -- 문제 원본 PDF 페이지
    bbox_x1 INTEGER,                        -- 바운딩 박스 좌상단 X
    bbox_y1 INTEGER,                        -- 바운딩 박스 좌상단 Y
    bbox_x2 INTEGER,                        -- 바운딩 박스 우하단 X
    bbox_y2 INTEGER,                        -- 바운딩 박스 우하단 Y

    -- 원본 위치 정보 (해설)
    solution_page INTEGER,                  -- 해설 원본 PDF 페이지
    solution_bbox_x1 INTEGER,
    solution_bbox_y1 INTEGER,
    solution_bbox_x2 INTEGER,
    solution_bbox_y2 INTEGER,

    -- 벡터 임베딩 (유사 문제 검색용)
    -- OpenAI text-embedding-3-small: 1536차원
    embedding vector(1536),

    -- 타임스탬프
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_questions_textbook ON questions(textbook_id);
CREATE INDEX IF NOT EXISTS idx_questions_theme ON questions(theme_id);
CREATE INDEX IF NOT EXISTS idx_questions_number ON questions(question_number);

-- 벡터 검색 인덱스 (IVFFlat)
CREATE INDEX IF NOT EXISTS idx_questions_embedding ON questions
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- 4. question_choices (선택지) - 문제용
-- ============================================================
CREATE TABLE IF NOT EXISTS question_choices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,

    label TEXT NOT NULL,                    -- 선택지 레이블 (①②③④⑤)
    text TEXT NOT NULL,                     -- 선택지 내용
    sort_order INTEGER DEFAULT 0,           -- 정렬 순서

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_question_choices_question ON question_choices(question_id);

-- ============================================================
-- 5. question_sub_items (보기/하위문항) - 문제용
-- ============================================================
CREATE TABLE IF NOT EXISTS question_sub_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,

    label TEXT NOT NULL,                    -- 보기 레이블 (ㄱ, ㄴ, ㄷ, (가), (나))
    text TEXT NOT NULL,                     -- 보기 내용
    sort_order INTEGER DEFAULT 0,           -- 정렬 순서

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_question_sub_items_question ON question_sub_items(question_id);

-- ============================================================
-- 6. question_figures (그래프/도형) - 문제용
-- ============================================================
CREATE TABLE IF NOT EXISTS question_figures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,

    -- 도형 유형
    figure_type TEXT,                       -- function_graph, geometry, number_line, etc.

    -- 위치 (문제 이미지 내 상대 좌표, 0~1)
    bbox_x1 REAL,
    bbox_y1 REAL,
    bbox_x2 REAL,
    bbox_y2 REAL,

    -- TikZ 코드 (재현용)
    tikz_code TEXT,

    -- 상세 데이터 (JSONB)
    figure_data JSONB,

    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_question_figures_question ON question_figures(question_id);
CREATE INDEX IF NOT EXISTS idx_question_figures_type ON question_figures(figure_type);

-- ============================================================
-- 7. solution_figures (그래프/도형 해석) - 해설용
-- ============================================================
CREATE TABLE IF NOT EXISTS solution_figures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,

    -- 도형 유형
    figure_type TEXT,                       -- function_graph, geometry, number_line, etc.

    -- 위치 (해설 이미지 내 상대 좌표, 0~1)
    bbox_x1 REAL,
    bbox_y1 REAL,
    bbox_x2 REAL,
    bbox_y2 REAL,

    -- TikZ 코드 (재현용)
    tikz_code TEXT,

    -- 상세 데이터 (JSONB)
    figure_data JSONB,

    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_solution_figures_question ON solution_figures(question_id);
CREATE INDEX IF NOT EXISTS idx_solution_figures_type ON solution_figures(figure_type);

-- ============================================================
-- 8. key_concepts (핵심 개념)
-- ============================================================
CREATE TABLE IF NOT EXISTS key_concepts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,

    concept_name TEXT NOT NULL,             -- 개념명 (예: "등차수열", "미분계수")

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_key_concepts_question ON key_concepts(question_id);
CREATE INDEX IF NOT EXISTS idx_key_concepts_name ON key_concepts(concept_name);

-- ============================================================
-- 9. 뷰: 문제 전체 정보 조회
-- ============================================================
CREATE OR REPLACE VIEW v_questions_full AS
SELECT
    q.id,
    q.question_number,
    q.question_text,
    q.answer,
    q.solution_text,
    q.source_page,
    q.solution_page,
    q.ai_model_id,
    q.ai_model_provider,
    q.created_at,

    -- 테마 정보
    t.id AS theme_id,
    t.name AS theme_name,
    t.color AS theme_color,

    -- 교재 정보
    tb.id AS textbook_id,
    tb.title AS textbook_title,
    tb.subject AS textbook_subject,
    tb.year AS textbook_year,
    tb.publisher AS textbook_publisher

FROM questions q
LEFT JOIN themes t ON q.theme_id = t.id
JOIN textbooks tb ON q.textbook_id = tb.id;

-- ============================================================
-- 10. 함수: 유사 문제 검색
-- ============================================================
CREATE OR REPLACE FUNCTION search_similar_questions(
    query_embedding vector(1536),
    match_threshold FLOAT DEFAULT 0.7,
    match_count INT DEFAULT 10,
    filter_textbook_id UUID DEFAULT NULL,
    filter_theme_id UUID DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    question_number TEXT,
    question_text TEXT,
    answer TEXT,
    solution_text TEXT,
    textbook_id UUID,
    textbook_title TEXT,
    theme_id UUID,
    theme_name TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.id,
        q.question_number,
        q.question_text,
        q.answer,
        q.solution_text,
        tb.id AS textbook_id,
        tb.title AS textbook_title,
        t.id AS theme_id,
        t.name AS theme_name,
        (1 - (q.embedding <=> query_embedding))::FLOAT AS similarity
    FROM questions q
    JOIN textbooks tb ON q.textbook_id = tb.id
    LEFT JOIN themes t ON q.theme_id = t.id
    WHERE
        q.embedding IS NOT NULL
        AND (filter_textbook_id IS NULL OR q.textbook_id = filter_textbook_id)
        AND (filter_theme_id IS NULL OR q.theme_id = filter_theme_id)
        AND (1 - (q.embedding <=> query_embedding)) > match_threshold
    ORDER BY q.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================
-- 11. 트리거: updated_at 자동 갱신
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- textbooks
DROP TRIGGER IF EXISTS update_textbooks_updated_at ON textbooks;
CREATE TRIGGER update_textbooks_updated_at
    BEFORE UPDATE ON textbooks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- themes
DROP TRIGGER IF EXISTS update_themes_updated_at ON themes;
CREATE TRIGGER update_themes_updated_at
    BEFORE UPDATE ON themes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- questions
DROP TRIGGER IF EXISTS update_questions_updated_at ON questions;
CREATE TRIGGER update_questions_updated_at
    BEFORE UPDATE ON questions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- 완료 메시지
-- ============================================================
-- 스키마 생성 완료! (v2 - 문제+해설 통합)
--
-- 다음 단계:
-- 1. Supabase 대시보드에서 이 SQL 실행
-- 2. .env 파일에 SUPABASE_URL, SUPABASE_KEY 설정
-- 3. Python 앱에서 연결 테스트
