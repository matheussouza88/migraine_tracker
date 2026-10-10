pipeline {
    agent any

    options {
        overrideIndexTriggers(true)
    }

    triggers {
        pollSCM('H * * * *')
    }

    environment {
        DOCKER_REGISTRY_HOST = 'ghcr.io'
        DOCKER_REGISTRY_OWNER = 'matheussouza88'
        DOCKER_REGISTRY = "${DOCKER_REGISTRY_HOST}/${DOCKER_REGISTRY_OWNER}"
        DOCKER_CREDENTIALS_ID = 'ghcr-auth'
        GIT_CREDENTIALS_ID = '0ba8a1cb-47ca-4104-9c3f-d66d67f99139'
        GITHUB_TOKEN_ID = 'ghcr-auth'
        
        IMAGE_NAME = "${DOCKER_REGISTRY}/migraine_tracker"
    }

    stages {
        stage('Initialize') {
            steps {
                script {
                    if (env.CHANGE_ID) {
                        echo "Pull Request detected: #${env.CHANGE_ID}"
                        updateGithubStatus('pending', 'Build started', 'Jenkins Build')
                    }
                }
            }
        }

        stage('Gitleaks Scan') {
            when {
                expression { env.CHANGE_ID != null }
            }
            steps {
                echo "Running Gitleaks security scan on pull request..."
                sh 'docker run --rm -v ${WORKSPACE}:/repo:ro zricethezav/gitleaks:latest detect --source=/repo --verbose'
            }
        }


        stage('Build & Test') {
            steps {
                script {
                    def imageTag = env.BRANCH_NAME == 'master' ? "v${env.BUILD_NUMBER}" : (env.CHANGE_ID ? "pr-${env.CHANGE_ID}-${env.BUILD_NUMBER}" : env.BRANCH_NAME)
                    env.IMAGE_TAG = imageTag.replaceAll("/", "-")

                    echo "Building Docker image for ${IMAGE_NAME}:${env.IMAGE_TAG}..."
                    sh "docker build -t ${IMAGE_NAME}:${env.IMAGE_TAG} ."

                    echo "Running pytest test suite in container..."
                    sh "docker run --rm ${IMAGE_NAME}:${env.IMAGE_TAG} pytest tests/ -v"
                }
            }
        }

        stage('Push to Registry') {
            when {
                branch 'master'
            }
            steps {
                script {
                    echo "Pushing Docker image to registry for master branch..."
                    withCredentials([usernamePassword(credentialsId: env.DOCKER_CREDENTIALS_ID, usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                        sh 'echo "$DOCKER_PASS" | docker login "$DOCKER_REGISTRY_HOST" -u "$DOCKER_USER" --password-stdin'
                        sh "docker push ${IMAGE_NAME}:${env.IMAGE_TAG}"
                        sh "docker tag ${IMAGE_NAME}:${env.IMAGE_TAG} ${IMAGE_NAME}:latest"
                        sh "docker push ${IMAGE_NAME}:latest"
                    }
                }
            }
        }

        stage('GitHub Approve & Merge') {
            when {
                expression { env.CHANGE_ID != null }
            }
            steps {
                script {
                    updateGithubStatus('success', 'Build successful', 'Jenkins Build')
                    approveGithubPullRequest(env.CHANGE_ID)
                    mergeGithubPullRequest(env.CHANGE_ID)
                }
            }
        }
    }

    post {
        success {
            echo "Build and deployment finished successfully!"
        }
        failure {
            script {
                if (env.CHANGE_ID) {
                    updateGithubStatus('failure', 'Build failed', 'Jenkins Build')
                }
            }
            echo "Build failed!"
        }
    }
}

def updateGithubStatus(state, description, context) {
    def gitUrl = env.GIT_URL ?: "git@github.com:matheussouza88/migraine_tracker.git"
    def repoPath = gitUrl.replace('git@github.com:', '').replace('https://github.com/', '').replace('.git', '')
    def sha = env.GIT_COMMIT ?: sh(script: 'git rev-parse HEAD', returnStdout: true).trim()

    withCredentials([usernamePassword(credentialsId: env.GITHUB_TOKEN_ID, usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
        sh """
            curl -f -s -X POST \\
                -H "Authorization: Bearer \$GH_PAT" \\
                -H "Accept: application/vnd.github.v3+json" \\
                https://api.github.com/repos/${repoPath}/statuses/${sha} \\
                -d '{"state": "${state.toLowerCase()}", "target_url": "${env.BUILD_URL}", "description": "${description}", "context": "${context}"}'
        """
    }
}

def approveGithubPullRequest(prId) {
    def gitUrl = env.GIT_URL ?: "git@github.com:matheussouza88/migraine_tracker.git"
    def repoPath = gitUrl.replace('git@github.com:', '').replace('https://github.com/', '').replace('.git', '')

    echo "Approving Pull Request #${prId} for ${repoPath}..."

    withCredentials([usernamePassword(credentialsId: env.GITHUB_TOKEN_ID, usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
        sh """
            curl -f -s -X POST \\
                -H "Authorization: Bearer \$GH_PAT" \\
                -H "Accept: application/vnd.github.v3+json" \\
                https://api.github.com/repos/${repoPath}/pulls/${prId}/reviews \\
                -d '{"event": "APPROVE", "body": "Jenkins Build Successful. Automatically approving PR."}' || true
        """
    }
}

def mergeGithubPullRequest(prId) {
    def gitUrl = env.GIT_URL ?: "git@github.com:matheussouza88/migraine_tracker.git"
    def repoPath = gitUrl.replace('git@github.com:', '').replace('https://github.com/', '').replace('.git', '')
    def branchName = env.CHANGE_BRANCH

    echo "Merging Pull Request #${prId} (branch: ${branchName}) for ${repoPath}..."

    withCredentials([usernamePassword(credentialsId: env.GITHUB_TOKEN_ID, usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
        sh """
            curl -f -s -X PUT \\
                -H "Authorization: Bearer \$GH_PAT" \\
                -H "Accept: application/vnd.github.v3+json" \\
                https://api.github.com/repos/${repoPath}/pulls/${prId}/merge \\
                -d '{"merge_method": "squash", "commit_title": "Auto-merge PR #${prId} after successful Jenkins build"}'
        """

        echo "Deleting branch ${branchName}..."
        sh """
            curl -f -s -X DELETE \\
                -H "Authorization: Bearer \$GH_PAT" \\
                -H "Accept: application/vnd.github.v3+json" \\
                https://api.github.com/repos/${repoPath}/git/refs/heads/${branchName}
        """
    }
}
