@echo off
setlocal enabledelayedexpansion

echo [1/4] Node.js 및 npm 설치 확인
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo npm^(winget^) 설치 중...
    winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
    
    echo Node.js 설치가 완료되었습니다.
    set "PATH=%PATH%;C:\Program Files\nodejs"
) else (
    echo npm이 이미 설치되어 있습니다.
)

echo.
echo [2/4] yarn 설치 확인
where yarn >nul 2>nul
if %errorlevel% neq 0 (
    echo yarn^(npm^) 설치 중...
    call npm install -g yarn
    
    set "PATH=%PATH%;%APPDATA%\npm"
) else (
    echo yarn이 이미 설치되어 있습니다.
)

echo.
echo [3/4] 프로젝트 의존성 패키지 설치
if exist "package.json" (
    echo package.json이 확인되었습니다. 'yarn install'을 실행합니다.
    call yarn install
) else (
    echo 오류: 현재 디렉토리에 package.json 파일이 없습니다.
    echo 올바른 프로젝트 폴더에서 이 스크립트를 실행해 주세요.
    pause
    exit /b
)

echo.
echo [4/4] 'yarn dev' 실행
call yarn dev

echo.
pause