# Google Sheets API 인증 설정 가이드

## 1. Google Cloud Console에서 서비스 계정 생성

### 1.1 Google Cloud Console 접속
- https://console.cloud.google.com/ 접속
- 프로젝트 선택 또는 새 프로젝트 생성

### 1.2 API 활성화
- "API 및 서비스" > "라이브러리" 메뉴로 이동
- 다음 API들을 검색하고 활성화:
  - Google Sheets API
  - Google Drive API

### 1.3 서비스 계정 생성
- "API 및 서비스" > "사용자 인증 정보" 메뉴로 이동
- "사용자 인증 정보 만들기" > "서비스 계정" 클릭
- 서비스 계정 이름 입력 (예: "image-voting-sheets")
- "만들고 계속하기" 클릭
- 역할 선택: "편집자" 또는 "뷰어" (읽기 전용인 경우)
- "완료" 클릭

### 1.4 서비스 계정 키 생성
- 생성된 서비스 계정 클릭
- "키" 탭으로 이동
- "키 추가" > "새 키 만들기" 클릭
- "JSON" 선택 후 "만들기" 클릭
- JSON 키 파일이 자동으로 다운로드됨

## 2. 서비스 계정 키 파일 설정

### 2.1 키 파일 배치
```bash
# 프로젝트 루트 디렉토리에 키 파일 복사
cp ~/Downloads/[다운로드된-키-파일명].json ./service-account-key.json
```

### 2.2 환경 변수로 설정 (선택사항)
```bash
export GOOGLE_SHEETS_CREDENTIALS_PATH="/path/to/your/service-account-key.json"
```

## 3. Google Sheets 공유 설정

### 3.1 스프레드시트 공유
- Google Sheets 문서 열기
- 우상단 "공유" 버튼 클릭
- 서비스 계정 이메일 주소 추가 (JSON 파일의 client_email 필드 확인)
- 권한: "뷰어" 또는 "편집자" 설정
- "완료" 클릭

### 3.2 서비스 계정 이메일 확인
```bash
# JSON 키 파일에서 client_email 확인
cat service-account-key.json | grep client_email
```

## 4. 보안 주의사항

### 4.1 키 파일 보안
- 서비스 계정 키 파일은 민감한 정보이므로 절대 Git에 커밋하지 마세요
- `.gitignore`에 추가:
```
service-account-key.json
*.json
```

### 4.2 환경 변수 사용 권장
- 프로덕션 환경에서는 환경 변수를 사용하여 키 파일 경로를 설정하세요
- 키 파일 자체는 안전한 위치에 저장하세요

## 5. 테스트

### 5.1 애플리케이션 실행
```bash
python app.py
```

### 5.2 API 엔드포인트 테스트
```bash
curl http://localhost:5000/api/profiles
```

## 6. 문제 해결

### 6.1 권한 오류 발생 시
- Google Sheets API가 활성화되었는지 확인
- 서비스 계정이 스프레드시트에 공유되었는지 확인
- 서비스 계정에 적절한 권한이 부여되었는지 확인

### 6.2 스코프 오류 발생 시
- 필요한 API 스코프가 포함되었는지 확인:
  - `https://www.googleapis.com/auth/spreadsheets.readonly`
  - `https://www.googleapis.com/auth/drive.readonly`
