# Image Voting Application

구글 AI 기반 스마트 애플리케이션 개발 프로젝트를 위한 이미지 투표 애플리케이션입니다.

## 환경 변수 설정

애플리케이션을 실행하기 전에 다음 환경 변수들을 설정해야 합니다:

### 1. 환경 변수 파일 생성

`env.example` 파일을 참고하여 `.env` 파일을 생성하세요:

```bash
cp env.example .env
```

### 2. 필수 환경 변수

`.env` 파일에 다음 값들을 설정하세요:

```env
# Google Cloud Storage Configuration
GCS_BUCKET_NAME=your-gcs-bucket-name

# Google Sheets Configuration
GOOGLE_SHEETS_ID=your-google-sheets-id
TEAM_SHEETS_ID=your-team-sheets-id

# Google Application Credentials (for Google Sheets API)
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/service-account-key.json
```

### 3. 서비스 계정 키 파일

Google Sheets API 접근을 위한 서비스 계정 키 파일을 준비하고 경로를 `GOOGLE_APPLICATION_CREDENTIALS`에 설정하세요.

## 보안 주의사항

- `.env` 파일은 절대 GitHub에 업로드하지 마세요
- 서비스 계정 키 파일은 안전하게 보관하세요
- 프로덕션 환경에서는 환경 변수를 직접 설정하세요

## 실행 방법

```bash
# Python 환경 설정
./setup_venv.sh

# 애플리케이션 실행
./run.sh
```

## 주요 기능

- 이미지 업로드 및 투표
- Google Sheets 연동 (프로필 및 팀 정보)
- 실시간 좋아요 기능
- 이미지 캐싱 시스템
