-- ============================================================
-- 스키마 변경: v1 → v2 (문제+해설 통합)
-- ============================================================
-- Supabase SQL Editor에서 실행
-- ============================================================

-- 0. 의존성 있는 뷰/함수 먼저 삭제
DROP VIEW IF EXISTS v_questions_full;
DROP FUNCTION IF EXISTS search_similar_questions(vector, float, int, uuid, uuid);

-- 1. questions 테이블에 새 컬럼 추가
ALTER TABLE questions ADD COLUMN IF NOT EXISTS solution_text TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS solution_page INTEGER;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS solution_bbox_x1 INTEGER;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS solution_bbox_y1 INTEGER;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS solution_bbox_x2 INTEGER;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS solution_bbox_y2 INTEGER;

-- 2. solution_figures 테이블 생성
CREATE TABLE IF NOT EXISTS solution_figures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    figure_type TEXT,
    bbox_x1 REAL,
    bbox_y1 REAL,
    bbox_x2 REAL,
    bbox_y2 REAL,
    tikz_code TEXT,
    figure_data JSONB,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_solution_figures_question ON solution_figures(question_id);
CREATE INDEX IF NOT EXISTS idx_solution_figures_type ON solution_figures(figure_type);

-- 3. 기존 데이터 정리 (type='해설'인 레코드 삭제)
DELETE FROM question_figures WHERE question_id IN (SELECT id FROM questions WHERE type = '해설');
DELETE FROM key_concepts WHERE question_id IN (SELECT id FROM questions WHERE type = '해설');
DELETE FROM question_choices WHERE question_id IN (SELECT id FROM questions WHERE type = '해설');
DELETE FROM question_sub_items WHERE question_id IN (SELECT id FROM questions WHERE type = '해설');
DELETE FROM questions WHERE type = '해설';

-- 4. 불필요한 컬럼 삭제
ALTER TABLE questions DROP COLUMN IF EXISTS type;
ALTER TABLE questions DROP COLUMN IF EXISTS linked_question_id;

-- 5. 불필요한 인덱스 삭제
DROP INDEX IF EXISTS idx_questions_type;
DROP INDEX IF EXISTS idx_questions_linked;

-- 6. 뷰 재생성
CREATE VIEW v_questions_full AS
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
    t.id AS theme_id,
    t.name AS theme_name,
    t.color AS theme_color,
    tb.id AS textbook_id,
    tb.title AS textbook_title,
    tb.subject AS textbook_subject,
    tb.year AS textbook_year,
    tb.publisher AS textbook_publisher
FROM questions q
LEFT JOIN themes t ON q.theme_id = t.id
JOIN textbooks tb ON q.textbook_id = tb.id;

-- 7. 유사 문제 검색 함수 재생성
CREATE FUNCTION search_similar_questions(
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
-- 완료! 확인 쿼리:
-- ============================================================
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'questions';
-- SELECT count(*) FROM questions;
