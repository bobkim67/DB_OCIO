// 관리자/클라이언트 권한 게이팅 (스텁).
//
// 현재는 로그인/인증 체계가 없어 admin 로그인을 가정한다(기본 admin=true).
// TODO(auth): 실제 로그인·권한 도입 시 이 함수를 세션/토큰 기반으로 교체.
//   그때 isAdmin=false 로 내려가면 Admin 탭은 자동으로 숨겨진다.
//
// 미리보기: URL 에 ?role=client 를 붙이면 클라이언트 화면(Admin 탭 숨김)을
// 확인할 수 있다. (그 외에는 admin 으로 간주)
export function useIsAdmin(): boolean {
  if (typeof window !== "undefined") {
    const role = new URLSearchParams(window.location.search).get("role");
    if (role === "client") return false;
  }
  return true;
}
