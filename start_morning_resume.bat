@echo off
chcp 65001 > nul
echo ============================================================
echo  아침 재개 오케스트레이터 (09:00+)
echo  단계: C' Image 나머지 stage → D 병합 → E Im재빌드
echo        F alpha조정 → G 평가 → H 보고서
echo ============================================================
echo.

cd /d "%~dp0App\backend"

REM 서버가 실행 중인지 확인 (평가를 위해 필요)
echo [확인] 검색 서버 (포트 5001) 실행 여부를 확인하세요.
echo         실행 안됐으면 별도 터미널에서: python app.py
echo.
timeout /t 5

python scripts\morning_resume.py

echo.
echo ============================================================
echo  [완료] 아침 재개 완료
echo  결과: md\_overnight_final_report.md
echo        md\_yplus_250_eval.md
echo        md\_xlang_50_eval.md
echo ============================================================
pause
