<script setup>
import { computed, nextTick, ref } from "vue";
import {
  getCourse,
  getCourses,
  login,
  materialUrl,
  resetAllProgress,
  resetTopicProgress,
  resolveCheckpoint,
  selectLearningTopic,
  sendAnswer,
} from "./api";

const userId = ref("");
const username = ref("");
const password = ref("");
const authError = ref("");
const authenticating = ref(false);
const courses = ref([]);
const workspace = ref(null);
const selectedCourseId = ref(null);
const loading = ref(true);
const sending = ref(false);
const error = ref("");
const draft = ref("");
const chatFeed = ref(null);
const visibleHistory = ref([]);
let animationGeneration = 0;

const analytics = computed(() => workspace.value?.analytics || {});
const displayName = computed(() =>
  userId.value
    ? userId.value.charAt(0).toUpperCase() + userId.value.slice(1)
    : "",
);
const userInitials = computed(() =>
  userId.value ? userId.value.slice(0, 2).toUpperCase() : "",
);

function scrollToLatest() {
  nextTick(() => {
    if (chatFeed.value) {
      chatFeed.value.scrollTop = chatFeed.value.scrollHeight;
    }
  });
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function revealAssistantMessage(message, generation) {
  const animatedMessage = {
    ...message,
    id: `animated-${message.id}-${Date.now()}`,
    content: "",
    streaming: true,
  };
  visibleHistory.value.push(animatedMessage);
  scrollToLatest();

  const characters = Array.from(message.content);
  const reduceMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  if (reduceMotion) {
    animatedMessage.content = message.content;
  } else {
    for (let index = 0; index < characters.length; index += 1) {
      if (generation !== animationGeneration) return;
      animatedMessage.content += characters[index];
      if (index % 4 === 0) {
        scrollToLatest();
        await wait(12);
      }
    }
  }

  animatedMessage.streaming = false;
  scrollToLatest();
}

async function loadCourses() {
  loading.value = true;
  error.value = "";
  try {
    courses.value = await getCourses(userId.value);
  } catch (requestError) {
    error.value = requestError.message;
  } finally {
    loading.value = false;
  }
}

async function submitLogin() {
  if (!username.value.trim() || !password.value || authenticating.value) return;
  authenticating.value = true;
  authError.value = "";
  try {
    const account = await login({
      username: username.value.trim(),
      password: password.value,
    });
    userId.value = account.user_id;
    password.value = "";
    await loadCourses();
  } catch (requestError) {
    authError.value = requestError.message;
  } finally {
    authenticating.value = false;
  }
}

function logout() {
  animationGeneration += 1;
  userId.value = "";
  username.value = "";
  password.value = "";
  authError.value = "";
  courses.value = [];
  selectedCourseId.value = null;
  workspace.value = null;
  visibleHistory.value = [];
  error.value = "";
}

async function openCourse(courseId) {
  loading.value = true;
  error.value = "";
  try {
    workspace.value = await getCourse(courseId, userId.value);
    visibleHistory.value = [...workspace.value.history];
    selectedCourseId.value = courseId;
    scrollToLatest();
  } catch (requestError) {
    error.value = requestError.message;
  } finally {
    loading.value = false;
  }
}

function closeCourse() {
  animationGeneration += 1;
  selectedCourseId.value = null;
  workspace.value = null;
  visibleHistory.value = [];
  error.value = "";
  loadCourses();
}

async function submitAnswer() {
  const message = draft.value.trim();
  const question = workspace.value?.current_question;
  if (!message || !question || sending.value) return;

  sending.value = true;
  error.value = "";
  draft.value = "";
  const previousHistory = [...visibleHistory.value];
  const optimisticId = `optimistic-user-${Date.now()}`;
  visibleHistory.value.push({
    id: optimisticId,
    role: "user",
    content: message,
  });
  visibleHistory.value.push({
    id: "coach-thinking",
    role: "assistant",
    content: "",
    thinking: true,
  });
  scrollToLatest();

  try {
    const response = await sendAnswer(selectedCourseId.value, {
      user_id: userId.value,
      question_id: question.id,
      message,
    });
    const userMessageIndex = response.history.findLastIndex(
      (item) => item.role === "user" && item.content === message,
    );
    const generatedMessages =
      userMessageIndex >= 0
        ? response.history
            .slice(userMessageIndex + 1)
            .filter((item) => item.role === "assistant")
        : [];

    workspace.value = response;
    visibleHistory.value = visibleHistory.value.filter(
      (item) => item.id !== "coach-thinking",
    );

    const generation = ++animationGeneration;
    for (const generatedMessage of generatedMessages) {
      await revealAssistantMessage(generatedMessage, generation);
    }

    if (generation === animationGeneration) {
      visibleHistory.value = [...response.history];
      scrollToLatest();
    }
  } catch (requestError) {
    visibleHistory.value = previousHistory;
    draft.value = message;
    error.value = requestError.message;
  } finally {
    sending.value = false;
  }
}

async function chooseCheckpoint(decision) {
  if (sending.value) return;
  sending.value = true;
  error.value = "";
  try {
    workspace.value = await resolveCheckpoint(selectedCourseId.value, {
      user_id: userId.value,
      decision,
    });
    visibleHistory.value = [...workspace.value.history];
    scrollToLatest();
  } catch (requestError) {
    error.value = requestError.message;
  } finally {
    sending.value = false;
  }
}

async function resetProgress(scope) {
  if (sending.value) return;
  const isCourseReset = scope === "course";
  const confirmed = window.confirm(
    isCourseReset
      ? "Reset all LearnLoop progress? Every answer, score, and knowledge gap will be deleted."
      : `Reset progress for “${analytics.value.current_topic}”? Answers and mastery for this topic will be deleted.`,
  );
  if (!confirmed) return;

  sending.value = true;
  error.value = "";
  animationGeneration += 1;
  try {
    workspace.value = isCourseReset
      ? await resetAllProgress(selectedCourseId.value, {
          user_id: userId.value,
          confirmed: true,
        })
      : await resetTopicProgress(selectedCourseId.value, {
          user_id: userId.value,
          topic: analytics.value.current_topic_id,
          confirmed: true,
        });
    visibleHistory.value = [...workspace.value.history];
    draft.value = "";
    scrollToLatest();
  } catch (requestError) {
    error.value = requestError.message;
  } finally {
    sending.value = false;
  }
}

async function selectTopic(topic) {
  if (sending.value || topic.current) return;
  sending.value = true;
  error.value = "";
  animationGeneration += 1;
  try {
    workspace.value = await selectLearningTopic(selectedCourseId.value, {
      user_id: userId.value,
      topic: topic.id,
    });
    visibleHistory.value = [...workspace.value.history];
    draft.value = "";
    scrollToLatest();
  } catch (requestError) {
    error.value = requestError.message;
  } finally {
    sending.value = false;
  }
}

function openMaterial(material) {
  window.open(
    materialUrl(selectedCourseId.value, material.id),
    "_blank",
    "noopener,noreferrer",
  );
}

</script>

<template>
  <main v-if="!userId" class="login-page">
    <section class="login-card">
      <div class="login-brand">
        <span class="brand-mark">L</span>
        <span>LearnLoop</span>
      </div>
      <p class="eyebrow">TEAM LEARNING SPACE</p>
      <h1>Welcome back</h1>
      <p class="login-copy">
        Sign in to continue your personal learning path.
      </p>

      <form class="login-form" @submit.prevent="submitLogin">
        <label>
          <span>Username</span>
          <input
            v-model="username"
            name="username"
            autocomplete="username"
            placeholder="Enter your username"
            autofocus
          />
        </label>
        <label>
          <span>Password</span>
          <input
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            placeholder="Enter your password"
          />
        </label>
        <p v-if="authError" class="login-error">{{ authError }}</p>
        <button
          type="submit"
          :disabled="!username.trim() || !password || authenticating"
        >
          {{ authenticating ? "Signing in…" : "Sign in" }}
        </button>
      </form>
    </section>
  </main>

  <main v-else-if="!selectedCourseId" class="library-page">
    <header class="library-header">
      <a class="brand" href="#" aria-label="LearnLoop home">
        <span class="brand-mark">L</span>
        <span>LearnLoop</span>
      </a>
      <div class="header-actions">
        <div class="profile-chip">
          <span class="status-dot"></span>
          <span>{{ displayName }}</span>
          <span class="avatar">{{ userInitials }}</span>
        </div>
        <button class="logout-button" type="button" @click="logout">
          Log out
        </button>
      </div>
    </header>

    <section class="hero">
      <p class="eyebrow">YOUR LEARNING SPACE</p>
      <h1>Keep learning.<br /><span>Stay in the loop.</span></h1>
      <p class="hero-copy">
        Your AI coach remembers what you know, finds the gaps, and chooses the
        next best thing to learn.
      </p>
    </section>

    <section class="courses-section">
      <div class="section-heading">
        <div>
          <p class="eyebrow">ACTIVE COURSES</p>
          <h2>Continue learning</h2>
        </div>
        <span class="course-count">{{ courses.length }} course</span>
      </div>

      <div v-if="loading" class="course-grid" aria-label="Loading courses">
        <div class="course-card skeleton"></div>
      </div>

      <div v-else class="course-grid">
        <button
          v-for="course in courses"
          :key="course.id"
          class="course-card"
          type="button"
          @click="openCourse(course.id)"
        >
          <div class="course-art">
            <span class="course-code">{{ course.short_title }}</span>
            <span class="book-stack" aria-hidden="true"></span>
          </div>
          <div class="course-body">
            <div class="course-meta">
              <span>{{ course.level }}</span>
              <span>{{ course.materials_count }} material</span>
            </div>
            <h3>{{ course.title }}</h3>
            <p>{{ course.description }}</p>
            <div class="progress-row">
              <div class="progress-track">
                <span
                  :style="{ width: `${course.analytics.course_completion}%` }"
                ></span>
              </div>
              <strong>{{ course.analytics.course_completion }}%</strong>
            </div>
            <div class="continue-link">
              Continue course <span aria-hidden="true">→</span>
            </div>
          </div>
        </button>
      </div>
    </section>

    <p v-if="error" class="error-banner">{{ error }}</p>
  </main>

  <main v-else-if="workspace" class="workspace">
    <header class="workspace-header">
      <button class="back-button" type="button" @click="closeCourse">
        <span aria-hidden="true">←</span> All courses
      </button>
      <div class="workspace-title">
        <span class="mini-course-code">{{ workspace.course.short_title }}</span>
        <div>
          <h1>{{ workspace.course.title }}</h1>
          <p>Adaptive learning session</p>
        </div>
      </div>
      <div class="profile-chip compact">
        <span class="status-dot"></span>
        <span>{{ displayName }}</span>
        <span class="avatar">{{ userInitials }}</span>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="materials-panel">
        <div class="panel-heading">
          <p class="eyebrow">COURSE LIBRARY</p>
          <h2>Materials</h2>
        </div>
        <button
          v-for="material in workspace.materials"
          :key="material.id"
          class="material-card"
          type="button"
          @click="openMaterial(material)"
        >
          <span class="pdf-icon">PDF</span>
          <span class="material-copy">
            <strong>{{ material.title }}</strong>
            <small>{{ material.status }}</small>
          </span>
          <span class="material-arrow">↗</span>
        </button>
        <div class="material-note">
          <span>i</span>
          <p>Course files are stored locally on your learning server.</p>
        </div>
      </aside>

      <section class="chat-panel">
        <div class="chat-heading">
          <div>
            <p class="eyebrow">PERSONAL AI COACH</p>
            <h2>Learning session</h2>
          </div>
          <span class="topic-pill">{{ analytics.current_topic }}</span>
        </div>

        <div ref="chatFeed" class="chat-feed">
          <article
            v-for="message in visibleHistory"
            :key="message.id"
            :class="['message-row', message.role]"
          >
            <span v-if="message.role === 'assistant'" class="coach-avatar">L</span>
            <div class="message">
              <span class="message-author">
                {{ message.role === "assistant" ? "LearnLoop" : "You" }}
              </span>
              <p v-if="message.thinking" class="thinking-dots" aria-label="LearnLoop is thinking">
                <span></span><span></span><span></span>
              </p>
              <p v-else :class="{ streaming: message.streaming }">
                {{ message.content }}
              </p>
              <span v-if="message.score !== undefined" class="score-badge">
                Score {{ message.score }}%
              </span>
            </div>
          </article>

          <div v-if="workspace.checkpoint" class="checkpoint-card">
            <p class="eyebrow">TOPIC CHECKPOINT</p>
            <h3>How confident do you feel?</h3>
            <div class="checkpoint-actions">
              <button
                v-if="
                  workspace.checkpoint.allowed_actions.includes('mark_mastered')
                "
                type="button"
                @click="chooseCheckpoint('mark_mastered')"
              >
                Mark as mastered
              </button>
              <button
                v-if="
                  workspace.checkpoint.allowed_actions.includes(
                    'one_more_question',
                  )
                "
                class="secondary"
                type="button"
                @click="chooseCheckpoint('one_more_question')"
              >
                One more question
              </button>
              <button
                v-if="
                  workspace.checkpoint.allowed_actions.includes('needs_review')
                "
                class="ghost"
                type="button"
                @click="chooseCheckpoint('needs_review')"
              >
                Review later
              </button>
            </div>
          </div>
        </div>

        <form class="composer" @submit.prevent="submitAnswer">
          <textarea
            v-model="draft"
            :disabled="!workspace.current_question || sending"
            :placeholder="
              workspace.current_question
                ? 'Write your answer…'
                : 'Complete the checkpoint to continue'
            "
            rows="2"
            @keydown.enter.exact.prevent="submitAnswer"
          ></textarea>
          <button
            type="submit"
            :disabled="
              !draft.trim() || !workspace.current_question || sending
            "
            aria-label="Send answer"
          >
            {{ sending ? "…" : "↑" }}
          </button>
        </form>
        <p v-if="error" class="inline-error">{{ error }}</p>
      </section>

      <aside class="analytics-panel">
        <div class="panel-heading">
          <p class="eyebrow">LEARNING PULSE</p>
          <h2>Your progress</h2>
        </div>

        <div class="completion-card">
          <div
            class="progress-ring"
            :style="{
              '--progress': `${analytics.course_completion * 3.6}deg`,
            }"
          >
            <div>
              <strong>{{ analytics.course_completion }}%</strong>
              <span>complete</span>
            </div>
          </div>
          <div>
            <span class="metric-label">COURSE PROGRESS</span>
            <p>One focused answer at a time.</p>
          </div>
        </div>

        <div class="topic-card">
          <span class="metric-label">CURRENT TOPIC</span>
          <h3>{{ analytics.current_topic }}</h3>
          <div class="progress-track large">
            <span :style="{ width: `${analytics.topic_completion}%` }"></span>
          </div>
          <div class="topic-stats">
            <span>
              {{ analytics.topic_questions_answered }}/{{
                analytics.topic_questions_target
              }}
              questions
            </span>
            <strong>{{ analytics.topic_mastery }}% mastery</strong>
          </div>
        </div>

        <div class="stat-grid">
          <div class="stat-card">
            <span class="stat-icon warm">✓</span>
            <strong>{{ analytics.questions_answered }}</strong>
            <span>Questions</span>
          </div>
          <div class="stat-card">
            <span class="stat-icon blue">◎</span>
            <strong>{{ analytics.average_score }}%</strong>
            <span>Avg. score</span>
          </div>
          <div class="stat-card">
            <span class="stat-icon green">↗</span>
            <strong>{{ analytics.learning_streak }}</strong>
            <span>Strong streak</span>
          </div>
          <div class="stat-card">
            <span class="stat-icon violet">◇</span>
            <strong>{{ analytics.knowledge_gaps?.length || 0 }}</strong>
            <span>Focus areas</span>
          </div>
        </div>

        <div v-if="analytics.knowledge_gaps?.length" class="focus-card">
          <span class="metric-label">FOCUS NEXT</span>
          <ul>
            <li v-for="gap in analytics.knowledge_gaps" :key="gap">
              {{ gap }}
            </li>
          </ul>
        </div>

        <div class="topics-card">
          <span class="metric-label">ALL TOPICS</span>
          <div class="topics-list">
            <button
              v-for="topic in analytics.topics"
              :key="topic.id"
              :class="['topic-row', { current: topic.current }]"
              type="button"
              :disabled="sending || topic.current"
              :aria-current="topic.current ? 'true' : undefined"
              @click="selectTopic(topic)"
            >
              <div class="topic-row-heading">
                <span>{{ topic.title }}</span>
                <strong>{{ topic.mastery }}%</strong>
              </div>
              <div class="progress-track topic-progress">
                <span :style="{ width: `${topic.mastery}%` }"></span>
              </div>
              <small class="topic-row-meta">
                {{ topic.questions_answered }}/{{ topic.questions_target }}
                answered · {{ topic.completion }}% coverage
              </small>
            </button>
          </div>
        </div>

        <div class="reset-actions">
          <button
            type="button"
            :disabled="sending"
            @click="resetProgress('topic')"
          >
            Reset current topic
          </button>
          <button
            class="danger"
            type="button"
            :disabled="sending"
            @click="resetProgress('course')"
          >
            Clear all progress
          </button>
        </div>
      </aside>
    </div>
  </main>

  <main v-else class="loading-screen">
    <div class="loading-mark">L</div>
    <p>Opening your course…</p>
  </main>
</template>
