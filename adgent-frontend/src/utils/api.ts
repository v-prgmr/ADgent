import { GenerateAdIdeasRequest, AdIdea } from "@/types/ad";

export type DraftSummary = {
  slug: string;
  has_storyboard: boolean;
  scenes: number;
  voiceovers: number;
  videos: number;
  final_video?: string | null;
};

export type DraftDetail = DraftSummary & {
  storyboard?: { scene_description: string; voice_over_text: string }[] | null;
  scene_images: string[];
  voiceover_files: string[];
  video_files: string[];
};

export const API_BASE_URL = "http://127.0.0.1:8000";

export async function generateAdIdeas(
  request: GenerateAdIdeasRequest
): Promise<AdIdea[]> {
  const response = await fetch(`${API_BASE_URL}/generate-ad-ideas`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  return await response.json();
}

export function extractUrl(text: string): string | null {
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const matches = text.match(urlRegex);
  return matches ? matches[0] : null;
}

export function websiteToSlug(website?: string): string {
  if (!website) return "default";
  let cleaned = website.trim().toLowerCase().replace(/^https?:\/\//, "");
  cleaned = cleaned.replace(/\//g, "-").replace(/[^a-z0-9._-]/g, "-");
  cleaned = cleaned.replace(/^[\-._]+|[\-._]+$/g, "");
  return cleaned || "default";
}

export async function generateStoryboard(
  selectedIdea: string,
  website?: string
): Promise<any> {
  const url = new URL(`${API_BASE_URL}/generate-story-board`);
  url.searchParams.set("selected_idea", selectedIdea);
  if (website) {
    url.searchParams.set("website", website);
  }
  const response = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: null,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  return await response.json();
}

export async function uploadCharAsset(
  file: File
): Promise<{ success: boolean; filename: string; path: string }> {
  const form = new FormData();
  form.append("image", file);
  const response = await fetch(`${API_BASE_URL}/upload-char-asset`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }
  return await response.json();
}

export async function generateScenes(
  storyboard: Array<{ scene_description: string; voice_over_text: string }>,
  website?: string
): Promise<any> {
  const url = new URL(`${API_BASE_URL}/generate-scenes`);
  if (website) {
    url.searchParams.set("website", website);
  }

  const response = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ storyboard }),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }
  return await response.json();
}

export async function regenerateScene(
  sceneIndex: number,
  prompt: string,
  website?: string
): Promise<any> {
  const url = new URL(`${API_BASE_URL}/regenerate-scene`);
  if (website) {
    url.searchParams.set("website", website);
  }

  const response = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ scene_index: sceneIndex, prompt }),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }
  return await response.json();
}

export async function generateVideos(website?: string): Promise<any> {
  const url = new URL(`${API_BASE_URL}/generate-videos`);
  if (website) {
    url.searchParams.set("website", website);
  }

  const response = await fetch(url.toString(), {
    method: "POST",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  return await response.json();
}

export async function generateVoiceovers(
  website?: string,
  voiceId?: string
): Promise<any> {
  const url = new URL(`${API_BASE_URL}/generate-voiceovers`);
  if (website) {
    url.searchParams.set("website", website);
  }
  if (voiceId) {
    url.searchParams.set("voice_id", voiceId);
  }

  const response = await fetch(url.toString(), {
    method: "POST",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  return await response.json();
}

export async function generateFinalVideo(website?: string): Promise<{ final_video?: string }> {
  const url = new URL(`${API_BASE_URL}/generate_final_video`);
  if (website) {
    url.searchParams.set("website", website);
  }

  const response = await fetch(url.toString(), {
    method: "POST",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  return await response.json();
}

export async function listDrafts(): Promise<DraftSummary[]> {
  const response = await fetch(`${API_BASE_URL}/drafts`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  const data = await response.json();
  return data?.drafts ?? [];
}

export async function loadDraft(slug: string): Promise<DraftDetail> {
  const response = await fetch(`${API_BASE_URL}/drafts/${slug}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  return await response.json();
}

export async function saveDraft(website?: string, slug?: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/drafts/save`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ website, slug }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  const data = await response.json();
  return data?.slug;
}
