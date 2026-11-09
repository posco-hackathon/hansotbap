# 프론트 반영 요청

백엔드의 데이터 계약(`app/backend/schemas.py`)이나 API 모양이 바뀌면, 프론트 `app/frontend/src/types.ts`에 반영할 내용을 이 폴더에 올립니다. 요청 하나에 파일 하나입니다.

- 파일 이름: `YYYYMMDD-F<번호>-<주제>.md` (예: `20261109-F4-adjustment-models.md`)
- 안에 적는 것: 상태, 브랜치, 바뀐 곳, `types.ts`에 붙여 넣을 TypeScript 코드, 쓰는 곳, API(있을 때)
- 상태: `미반영` → 프론트에서 반영하면 같은 PR에서 `반영됨`으로 바꿉니다. 파일은 지우지 않습니다.
- 아직 반영 안 된 요청 찾기: `grep -l "상태: 미반영" docs/frontend-requests/*.md`
