const axios = require("axios");

const http = axios.create({
  timeout: 20000,
  headers: {
    "User-Agent":
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    Accept: "text/html,application/json;q=0.9,*/*;q=0.8",
  },
});

function wait(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function parseRetryAfterMs(retryAfterValue) {
  if (!retryAfterValue) return null;
  const asNumber = Number(retryAfterValue);
  if (Number.isFinite(asNumber) && asNumber >= 0) {
    return asNumber * 1000;
  }
  const asDate = new Date(retryAfterValue);
  if (!Number.isNaN(asDate.getTime())) {
    const delta = asDate.getTime() - Date.now();
    return delta > 0 ? delta : null;
  }
  return null;
}

function shouldRetry(error) {
  const status = error?.response?.status;
  const code = error?.code;
  if (status === 429) return true;
  if (Number.isFinite(status) && status >= 500) return true;
  return (
    code === "ECONNABORTED" ||
    code === "ECONNRESET" ||
    code === "ETIMEDOUT" ||
    code === "EAI_AGAIN"
  );
}

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error?.config || {};
    const method = String(config.method || "get").toLowerCase();
    if (method !== "get" || !shouldRetry(error)) {
      throw error;
    }

    config.__retryCount = (config.__retryCount || 0) + 1;
    const maxRetries = 4;
    if (config.__retryCount > maxRetries) {
      throw error;
    }

    const retryAfterMs = parseRetryAfterMs(error?.response?.headers?.["retry-after"]);
    const backoffMs =
      retryAfterMs ??
      Math.round(800 * 2 ** (config.__retryCount - 1) + Math.random() * 250);
    await wait(backoffMs);
    return http(config);
  },
);

module.exports = {
  http,
};
