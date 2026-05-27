// Jenkins Pipeline — Playwright + Allure + TCRT callback
//
// Drop into a Pipeline job. TCRT injects `tcrt_run_id` and `NODE_LABEL` when
// triggering. NODE_LABEL controls runner placement; `tcrt_run_id` is echoed
// back to the inbound webhook for correlation.

pipeline {
    agent { label "${params.NODE_LABEL ?: 'any'}" }
    parameters {
        string(name: 'tcrt_run_id', description: 'TCRT correlation id')
        string(name: 'NODE_LABEL', defaultValue: 'any', description: 'Runner label')
        text(name: 'test_paths', defaultValue: 'tests/', description: 'Space-separated test paths')
    }
    environment {
        TCRT_BASE_URL = credentials('tcrt-base-url')
        TCRT_WEBHOOK_TOKEN = credentials('tcrt-webhook-token')
        TCRT_WEBHOOK_SECRET = credentials('tcrt-webhook-secret')
    }
    stages {
        stage('Setup') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install -r requirements.txt
                    pip install allure-pytest pytest-playwright
                    python -m playwright install --with-deps chromium
                '''
            }
        }
        stage('Test') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pytest ${test_paths} --alluredir=allure-results || true
                '''
            }
        }
        stage('Report') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pip install allure-commandline || true
                    allure generate allure-results --clean -o allure-report
                '''
                publishHTML(target: [
                    reportDir: 'allure-report',
                    reportFiles: 'index.html',
                    reportName: 'Allure Report',
                    keepAll: true
                ])
            }
        }
    }
    post {
        always {
            script {
                def status = currentBuild.currentResult == 'SUCCESS' ? 'SUCCEEDED' :
                             currentBuild.currentResult == 'UNSTABLE' ? 'FAILED' :
                             currentBuild.currentResult == 'ABORTED' ? 'CANCELLED' : 'FAILED'
                def payload = groovy.json.JsonOutput.toJson([
                    tcrt_run_id: params.tcrt_run_id,
                    status: status,
                    external_run_url: env.BUILD_URL,
                    duration_ms: currentBuild.duration
                ])
                sh """
                    SIG=\$(printf '%s' '${payload}' | openssl dgst -sha256 -hmac \"\$TCRT_WEBHOOK_SECRET\" | awk '{print \$2}')
                    curl -fsS -X POST \\
                      \"\$TCRT_BASE_URL/api/v1/webhooks/ci/\$TCRT_WEBHOOK_TOKEN/run-status\" \\
                      -H 'Content-Type: application/json' \\
                      -H \"X-TCRT-Signature: sha256=\$SIG\" \\
                      -H 'X-TCRT-Delivery: ${env.BUILD_NUMBER}' \\
                      -d '${payload}'
                """
            }
        }
    }
}
