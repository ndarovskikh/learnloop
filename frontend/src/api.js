const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message || "The learning service returned an error.";
    throw new Error(message);
  }
  return response.json();
}

export function login(payload) {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCourses(userId) {
  return request(`/api/courses?user_id=${encodeURIComponent(userId)}`);
}

export function getCourse(courseId, userId) {
  return request(
    `/api/courses/${courseId}?user_id=${encodeURIComponent(userId)}`,
  );
}

export function sendAnswer(courseId, payload) {
  return request(`/api/courses/${courseId}/messages`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resolveCheckpoint(courseId, payload) {
  return request(`/api/courses/${courseId}/checkpoint`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generatePracticeQuestions(courseId, payload) {
  return request(`/api/courses/${courseId}/practice-questions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resetAllProgress(courseId, payload) {
  return request(`/api/courses/${courseId}/reset`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resetTopicProgress(courseId, payload) {
  return request(`/api/courses/${courseId}/reset-topic`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function selectLearningTopic(courseId, payload) {
  return request(`/api/courses/${courseId}/select-topic`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function materialUrl(courseId, materialId) {
  return `${API_URL}/api/courses/${courseId}/materials/${materialId}`;
}
