// 이행 기록(제64조)에 남는 "누가". 한 번 적으면 조정·공유·공지·TBM 확인 패널이 같은 이름을 쓴다 (탭을 닫으면 지워짐)
import { useState } from "react";

const KEY = "hansotbap.decidedBy"; // ConflictList 조정안 패널과 같은 키

function read(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function usePerson(): [string, (name: string) => void] {
  const [name, setName] = useState(read);
  const update = (v: string) => {
    setName(v);
    try {
      sessionStorage.setItem(KEY, v.trim());
    } catch {
      // 저장소를 못 쓰면 이 화면에서만 기억한다
    }
  };
  return [name, update];
}
