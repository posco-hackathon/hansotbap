# F4 조정안·재판정 모델 추가

- 상태: 미반영
- 브랜치: `feat/F4-adjust` (`feat/F2-conflict-rules` 위에 쌓음)
- 바뀐 곳: `app/backend/schemas.py`에 `AdjustmentKind`, `AdjustmentCandidate`, `Adjustment`, `ConflictGradeChange`, `ConflictDiff`를 더했습니다. 기존 모델은 바뀌지 않았습니다.
- 쓰는 곳 / 까닭: 충돌 상세 화면의 조정안 카드와 [조정 적용] 버튼(기획서 F4), 적용 뒤 "사라짐 / 새로 생김" 표시, 이력(F5)의 조정 기록.
- API: 아직 없습니다. 엔드포인트가 생기면 새 요청 파일로 올립니다.

## `types.ts`에 이렇게 추가해 주세요

기존 `Grade`, `Conflict`를 쓰므로 `Conflict` 아래에 붙입니다.

```ts
export type AdjustmentKind = "reschedule";

// F4 조정안 후보: 규칙이 계산한 일정 이동안
export interface AdjustmentCandidate {
  id: string;
  kind: AdjustmentKind;
  task_id: string; // 옮길 작업
  conflict_id: string; // 이 조정안이 풀려는 충돌
  original_start: string; // ISO datetime
  original_end: string;
  new_start: string;
  new_end: string;
  reason: string;
  resolves: boolean; // 적용하면 conflict_id의 충돌이 사라지는가
  new_conflict_ids: string[]; // 적용하면 새로 생기는 충돌
  affected_successors: string[]; // 옮긴 뒤 시작이 이 작업의 새 종료보다 이른 후행 작업
}

// 적용한 조정 기록: 협력사 원본 계획서는 그대로 두고 이 기록을 얹어 판정한다
export interface Adjustment {
  id: string;
  kind: AdjustmentKind;
  task_id: string;
  conflict_id: string;
  original_start: string;
  original_end: string;
  new_start: string;
  new_end: string;
  reason: string;
  decided_by: string; // 적용한 책임자
  decided_at: string;
}

export interface ConflictGradeChange {
  conflict_id: string;
  before: Grade;
  after: Grade;
}

// 조정 전후 비교 (Conflict.id 기준)
export interface ConflictDiff {
  resolved: Conflict[]; // 사라진 충돌
  introduced: Conflict[]; // 새로 생긴 충돌
  grade_changed: ConflictGradeChange[];
}
```
