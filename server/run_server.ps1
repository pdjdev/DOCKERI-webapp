# 1. 가상 환경 활성화 스크립트 경로 설정
$venvPath = ".\.venv\Scripts\Activate.ps1"

# 2. 가상 환경 파일 존재 여부 확인
if (Test-Path $venvPath) {
    Write-Host "가상 환경을 활성화하고 서버를 시작합니다..." -ForegroundColor Cyan
    
    # 가상 환경 활성화 (Dot sourcing 사용)
    . $venvPath
    
    # 3. uvicorn 서버 실행 (새로운 모듈 구조)
    uvicorn app.main:app --reload
}
else {
    Write-Host "오류: .venv 폴더를 찾을 수 없습니다. 경로를 확인해주세요." -ForegroundColor Red
}