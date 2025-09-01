## 2. Application Default Credentials 설정

### 2.1 로그인 및 인증
```bash
# Google 계정으로 로그인
gcloud auth login

# Application Default Credentials 설정 (올바른 스코프 포함)
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/spreadsheets.readonly,https://www.googleapis.com/auth/drive.readonly

# 또는 기본 설정 후 스코프 추가
gcloud auth application-default login
```

### 2.2 인증 상태 확인
```bash
# 현재 인증된 계정 확인
gcloud auth list

# Application Default Credentials 확인
gcloud auth application-default print-access-token

# 현재 설정된 스코프 확인
gcloud auth application-default print-access-token --scopes=https://www.googleapis.com/auth/spreadsheets.readonly
```
