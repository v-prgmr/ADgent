import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatMessage } from "@/components/ChatMessage";
import { ChatInput } from "@/components/ChatInput";
import { ProcessingSteps } from "@/components/ProcessingSteps";
import { AdIdeasGrid } from "@/components/AdIdeasGrid";
import {
  StoryboardPanel,
  type StoryboardScene,
} from "@/components/StoryboardPanel";
import {
  CharAssetsUploader,
  type UploadedAsset,
} from "@/components/CharAssetsUploader";
import { ScenesGenerationPanel } from "@/components/ScenesGenerationPanel";
import { ScenesGallery } from "@/components/ScenesGallery";
import { TopProgressBar } from "@/components/TopProgressBar";
import { AppSidebar } from "@/components/AppSidebar";
import { SourcesInput } from "@/components/SourcesInput";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Loader2, Maximize2 } from "lucide-react";
import {
  API_BASE_URL,
  generateAdIdeas,
  extractUrl,
  generateStoryboard,
  listDrafts,
  loadDraft,
  saveDraft,
  websiteToSlug,
  type DraftDetail,
  type DraftSummary,
} from "@/utils/api";
import { AdIdea, ProcessingStep } from "@/types/ad";
import { useNavigate } from "react-router-dom";

interface Message {
  role: "user" | "assistant";
  content: string;
  typing?: boolean;
  ephemeral?: boolean;
  fade?: boolean;
}

type LeftNavKey = "new" | "storyboard" | "scenes" | "drafts" | "voiceover" | "all" | "assets";

const TYPING_MS_PER_CHAR = 18;

const Index = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingSteps, setProcessingSteps] = useState<ProcessingStep[]>([]);
  const [adIdeas, setAdIdeas] = useState<AdIdea[]>([]);
  const [selectedIdeaIndex, setSelectedIdeaIndex] = useState<number | null>(
    null
  );
  const [companyUrl, setCompanyUrl] = useState<string>("");
  const [prefillMessage, setPrefillMessage] = useState<string>("");
  const [routeNextToStoryboard, setRouteNextToStoryboard] =
    useState<boolean>(false);
  const [storyboardResult, setStoryboardResult] = useState<{
    prompt: string;
    generated_text: string;
    model?: string;
  } | null>(null);
  const [storyboardScenes, setStoryboardScenes] = useState<
    StoryboardScene[] | null
  >(null);
  const [lastStoryboardText, setLastStoryboardText] = useState<string>("");
  const [charAssets, setCharAssets] = useState<UploadedAsset[]>([]);
  const [isGeneratingScenes, setIsGeneratingScenes] = useState<boolean>(false);
  const [generatedSceneUrls, setGeneratedSceneUrls] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [showSources, setShowSources] = useState<boolean>(false);
  const [isGeneratingVideo, setIsGeneratingVideo] = useState<boolean>(false);
  const [isGeneratingVoiceovers, setIsGeneratingVoiceovers] =
    useState<boolean>(false);
  const [isCombiningScenes, setIsCombiningScenes] = useState<boolean>(false);
  const [isVideoReady, setIsVideoReady] = useState<boolean>(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [availableVideos, setAvailableVideos] = useState<string[]>([]);
  const [currentVideoIndex, setCurrentVideoIndex] = useState<number>(0);
  const [videoGenerationResults, setVideoGenerationResults] = useState<any[]>(
    []
  );
  const [voiceoverUrls, setVoiceoverUrls] = useState<string[]>([]);
  const [activeNav, setActiveNav] = useState<LeftNavKey>("new");
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [selectedDraftSlug, setSelectedDraftSlug] = useState<string | null>(
    null
  );
  const [isLoadingDraft, setIsLoadingDraft] = useState<boolean>(false);
  const [currentSlug, setCurrentSlug] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const navigate = useNavigate();
  const toAbsoluteUrl = useCallback((path?: string | null) => {
    if (!path) return "";
    if (path.startsWith("http")) return path;
    const normalized = path.startsWith("/") ? path : `/${path}`;
    return `${API_BASE_URL}${normalized}`;
  }, []);
  const hasSceneVideos = useMemo(
    () =>
      videoGenerationResults.some(
        (item: any) => item?.status === "success" || item?.status === "existing"
      ),
    [videoGenerationResults]
  );
  const handleRegenerateImage = async (sceneIndex: number, prompt: string) => {
    const { regenerateScene, API_BASE_URL, websiteToSlug } = await import(
      "@/utils/api"
    );
    const slug = websiteToSlug(companyUrl);
    await regenerateScene(sceneIndex, prompt, companyUrl || undefined);
    // Bust cache for updated image
    setGeneratedSceneUrls((prev) =>
      prev.map((u, idx) =>
        idx + 1 === sceneIndex
          ? `${API_BASE_URL}/generated_scenes/${slug}/images/scene${sceneIndex}.png?t=${Date.now()}`
          : u
      )
    );
  };

  const resetWorkspace = useCallback(() => {
    setMessages([]);
    setProcessingSteps([]);
    setAdIdeas([]);
    setSelectedIdeaIndex(null);
    setCompanyUrl("");
    setPrefillMessage("");
    setRouteNextToStoryboard(false);
    setStoryboardResult(null);
    setStoryboardScenes(null);
    setLastStoryboardText("");
    setCharAssets([]);
    setIsGeneratingScenes(false);
    setGeneratedSceneUrls([]);
    setIsGeneratingVideo(false);
    setIsVideoReady(false);
    setVideoUrl(null);
    setAvailableVideos([]);
    setCurrentVideoIndex(0);
    setVideoGenerationResults([]);
    setVoiceoverUrls([]);
    setSelectedDraftSlug(null);
    setCurrentSlug(null);
  }, []);

  const refreshDrafts = useCallback(async () => {
    try {
      const items = await listDrafts();
      setDrafts(items);
    } catch (error) {
      console.error("Error loading drafts", error);
      toast.error(
        error instanceof Error ? error.message : "Unable to load drafts"
      );
    }
  }, []);

  const handleDraftSelect = useCallback(
    async (slug: string) => {
      setIsLoadingDraft(true);
      try {
        const detail: DraftDetail = await loadDraft(slug);
        setSelectedDraftSlug(slug);
        setCompanyUrl(slug);
        setCurrentSlug(slug);
        setAdIdeas([]);
        setSelectedIdeaIndex(null);
        setMessages([]);
        setPrefillMessage("");
        setStoryboardResult(null);
        setStoryboardScenes(detail.storyboard ?? null);
        setGeneratedSceneUrls(detail.scene_images.map((url) => toAbsoluteUrl(url)));
        setVoiceoverUrls(
          (detail.voiceover_files || []).map((url) => toAbsoluteUrl(url))
        );

        const videos = (detail.video_files || []).map((url) =>
          toAbsoluteUrl(url)
        );
        const finalVideo = detail.final_video
          ? toAbsoluteUrl(detail.final_video)
          : null;

        const allVideos = finalVideo ? [finalVideo, ...videos] : videos;
        setAvailableVideos(allVideos);
        setVideoUrl(allVideos[0] || null);
        setIsVideoReady(allVideos.length > 0);
        setActiveNav("storyboard");
        toast.success(`Loaded draft: ${slug}`);
      } catch (error) {
        console.error("Error loading draft", error);
        toast.error(
          error instanceof Error ? error.message : "Failed to load draft"
        );
      } finally {
        setIsLoadingDraft(false);
      }
    },
    [toAbsoluteUrl]
  );

  const handleSaveDraftAndReset = useCallback(async () => {
    const slug = currentSlug || (companyUrl ? websiteToSlug(companyUrl) : selectedDraftSlug);

    if (!slug) {
      resetWorkspace();
      setActiveNav("new");
      return;
    }

    try {
      await saveDraft(companyUrl || undefined, slug);
      await refreshDrafts();
      toast.success("Current work saved to drafts");
    } catch (error) {
      console.error("Error saving draft", error);
      toast.error(error instanceof Error ? error.message : "Failed to save draft");
    } finally {
      resetWorkspace();
      setActiveNav("new");
    }
  }, [companyUrl, currentSlug, refreshDrafts, resetWorkspace, selectedDraftSlug]);

  const handleSidebarNavigate = useCallback(
    (target: LeftNavKey) => {
      switch (target) {
        case "new":
          void handleSaveDraftAndReset();
          break;
        case "drafts":
          setActiveNav("drafts");
          void refreshDrafts();
          break;
        case "storyboard":
        case "scenes":
        case "voiceover":
          setActiveNav(target);
          break;
        default:
          setActiveNav(target);
      }
    },
    [handleSaveDraftAndReset, refreshDrafts]
  );

  const handleCreateVideo = async () => {
    if (generatedSceneUrls.length === 0) {
      toast.error("Generate scenes before creating a video");
      return;
    }

    setIsVideoReady(false);
    setVideoUrl(null);
    setAvailableVideos([]);
    setCurrentVideoIndex(0);
    setIsGeneratingVideo(true);

    try {
      const { generateVideos, websiteToSlug, API_BASE_URL } = await import(
        "@/utils/api"
      );
      const response = await generateVideos(companyUrl || undefined);
      setVideoGenerationResults(response?.results ?? []);
      const slug = websiteToSlug(companyUrl);
      const playableUrls = (response?.results ?? [])
        .filter(
          (item: any) => item?.status === "success" || item?.status === "existing"
        )
        .map((item: any) => {
          if (item?.public_url) {
            return `${API_BASE_URL}${item.public_url}`;
          }
          const sceneNumber = item?.scene ?? 1;
          return `${API_BASE_URL}/generated_scenes/${slug}/video/scene${sceneNumber}.mp4`;
        });

      if (playableUrls.length > 0) {
        setAvailableVideos(playableUrls);
        setCurrentVideoIndex(0);
        setVideoUrl(playableUrls[0]);
        setIsVideoReady(true);
        toast.success("Video generated");
      } else {
        toast.error("Video generation failed for all scenes");
      }
    } catch (error) {
      console.error("Error generating video:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to generate video"
      );
    } finally {
      setIsGeneratingVideo(false);
    }
  };

  const handleGenerateVoiceovers = async () => {
    setIsGeneratingVoiceovers(true);
    try {
      const { generateVoiceovers } = await import("@/utils/api");
      const result = await generateVoiceovers(companyUrl || undefined);
      const successCount = result?.successful ?? 0;
      const total = result?.total_scenes ?? 0;
      toast.success(
        `Generated voiceovers for ${successCount}/${total || "all"} scenes`
      );
      const slug = companyUrl || selectedDraftSlug;
      if (slug) {
        loadDraft(websiteToSlug(slug))
          .then((detail) =>
            setVoiceoverUrls(
              (detail.voiceover_files || []).map((url) => toAbsoluteUrl(url))
            )
          )
          .catch((error) => {
            console.error("Failed to refresh voiceovers", error);
          });
      }
    } catch (error) {
      console.error("Error generating voiceovers:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to generate voiceovers"
      );
    } finally {
      setIsGeneratingVoiceovers(false);
    }
  };

  const handleCombineScenes = async () => {
    setIsCombiningScenes(true);
    try {
      const { generateFinalVideo, API_BASE_URL } = await import("@/utils/api");
      const { final_video } = await generateFinalVideo(companyUrl || undefined);
      if (final_video) {
        const finalVideoUrl = `${API_BASE_URL}/${final_video.replace(/^\//, "")}`;
        setVideoUrl(finalVideoUrl);
        setAvailableVideos([finalVideoUrl]);
        setCurrentVideoIndex(0);
        setIsVideoReady(true);
        toast.success("Final video created");
        saveDraft(companyUrl || undefined, currentSlug || undefined).catch(() => {
          // non-blocking
        });
      } else {
        toast.error("Failed to create final video");
      }
    } catch (error) {
      console.error("Error combining scenes:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to combine scenes"
      );
    } finally {
      setIsCombiningScenes(false);
    }
  };

  const handleEnterFullscreen = () => {
    const el = videoRef.current;
    if (!el) return;
    if (el.requestFullscreen) {
      el.requestFullscreen();
    } else {
      // Fallback: open controls-only fullscreen via webkit if available
      // @ts-expect-error vendor api
      if (el.webkitEnterFullscreen) {
        // @ts-expect-error vendor api
        el.webkitEnterFullscreen();
      }
    }
  };

  const activeVideoUrl = useMemo(
    () => availableVideos[currentVideoIndex] ?? videoUrl,
    [availableVideos, currentVideoIndex, videoUrl]
  );

  const handlePrevVideo = () => {
    setCurrentVideoIndex((prev) => (prev > 0 ? prev - 1 : prev));
  };

  const handleNextVideo = () => {
    setCurrentVideoIndex((prev) =>
      prev < availableVideos.length - 1 ? prev + 1 : prev
    );
  };

  const updateStepStatus = (
    stepId: string,
    status: ProcessingStep["status"]
  ) => {
    setProcessingSteps((prev) =>
      prev.map((step) => (step.id === stepId ? { ...step, status } : step))
    );
  };

  const handleSendMessage = async (message: string) => {
    // If we flagged the next submit to create a storyboard, route to that endpoint
    if (routeNextToStoryboard) {
      try {
        // Clear any existing ad ideas view
        setAdIdeas([]);
        setSelectedIdeaIndex(null);
        setStoryboardResult(null);
        setStoryboardScenes(null);

        // Initialize storyboard steps
        const steps: ProcessingStep[] = [
          {
            id: "prepare",
            label: "Preparing storyboard prompt",
            status: "processing",
          },
          { id: "generate", label: "Generating storyboard", status: "pending" },
          { id: "finalize", label: "Finalizing", status: "pending" },
        ];
        setProcessingSteps(steps);
        setIsProcessing(true);

        setMessages((prev) => [
          ...prev,
          { role: "user", content: message },
          {
            role: "assistant",
            content: "Sure, I’ll generate a storyboard from that.",
            typing: true,
            ephemeral: true,
          },
        ]);
        // Initialize storyboard steps (all pending – first pill appears after typing)
        setProcessingSteps([
          {
            id: "prepare",
            label: "Preparing storyboard prompt",
            status: "pending",
          },
          { id: "generate", label: "Generating storyboard", status: "pending" },
          { id: "finalize", label: "Finalizing", status: "pending" },
        ]);
        setIsProcessing(true);
        // Wait for typing animation to finish before showing first pill
        const storyboardPreface = "Sure, I’ll generate a storyboard from that.";
        await new Promise((resolve) =>
          setTimeout(
            resolve,
            storyboardPreface.length * TYPING_MS_PER_CHAR + 120
          )
        );
        // Now show first pill briefly, then proceed
        updateStepStatus("prepare", "processing");
        await new Promise((resolve) => setTimeout(resolve, 900));
        updateStepStatus("prepare", "complete");
        updateStepStatus("generate", "processing");

        // Track exact user text for regenerate (no template)
        setLastStoryboardText(message);
        const res = await generateStoryboard(message, companyUrl || undefined);

        updateStepStatus("generate", "complete");
        updateStepStatus("finalize", "processing");

        setStoryboardResult({
          prompt: res.prompt,
          generated_text: res.generated_text,
          model: res.model,
        });
        // Parse scenes from generated_text
        try {
          const parsed = JSON.parse(res.generated_text);
          if (Array.isArray(parsed)) {
            const normalized: StoryboardScene[] = parsed
              .filter(
                (s: any) =>
                  s &&
                  typeof s.scene_description === "string" &&
                  typeof s.voice_over_text === "string"
              )
              .map((s: any) => ({
                scene_description: s.scene_description,
                voice_over_text: s.voice_over_text,
              }));
            setStoryboardScenes(normalized);
          } else {
            setStoryboardScenes(null);
          }
        } catch {
          setStoryboardScenes(null);
        }

        // Fade out ephemeral preface + steps, then append final message
        setMessages((prev) =>
          prev.map((m) => (m.ephemeral ? { ...m, fade: true } : m))
        );
        setTimeout(() => {
          setMessages((prev) => [
            ...prev.filter((m) => !m.ephemeral),
            {
              role: "assistant",
              content:
                "Storyboard generated. Review it below or click Regenerate to refine.",
            },
          ]);
        }, 500);
        toast.success("Storyboard generated!");
        // Reset routing flag and prefill
        setRouteNextToStoryboard(false);
        setPrefillMessage("");
        updateStepStatus("finalize", "complete");
      } catch (error) {
        console.error("Error generating storyboard:", error);
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to generate storyboard"
        );
      } finally {
        setIsProcessing(false);
      }
      return;
    }

    // Extract URL from message
    const url = extractUrl(message);

    if (!url) {
      toast.error("Please include a company website URL in your message");
      return;
    }

    setCompanyUrl(url);
    setCurrentSlug(websiteToSlug(url));

    // Add user message
    const host = (() => {
      try {
        return new URL(url).host;
      } catch {
        return url.replace(/^https?:\/\//, "");
      }
    })();
    setMessages((prev) => [
      ...prev,
      { role: "user", content: message },
      {
        role: "assistant",
        content: `Sure, I will generate ad concepts for ${host}`,
        typing: true,
        ephemeral: true,
      },
    ]);

    // Extract additional context (everything except the URL)
    const additionalContext = message.replace(url, "").trim();
    const combinedContext = [
      additionalContext,
      sources.length > 0 ? `Additional sources: ${sources.join(", ")}` : "",
    ]
      .filter(Boolean)
      .join(" ");

    // Initialize processing steps (all pending – first pill appears after typing)
    const steps: ProcessingStep[] = [
      { id: "scrape", label: "Scraping company website", status: "pending" },
      {
        id: "analyze",
        label: "Analyzing company information",
        status: "pending",
      },
      { id: "generate", label: "Generating ad concepts", status: "pending" },
      { id: "images", label: "Creating visual designs", status: "pending" },
    ];

    setProcessingSteps(steps);
    setIsProcessing(true);
    setAdIdeas([]);
    setSelectedIdeaIndex(null);
    setStoryboardResult(null);
    setStoryboardScenes(null);

    try {
      // Wait for the typing animation before showing first pill
      const preface = `Sure, I will generate ad concepts for ${host}`;
      await new Promise((resolve) =>
        setTimeout(resolve, preface.length * TYPING_MS_PER_CHAR + 120)
      );
      // Simulate step-by-step processing (sequential, pills appear one-by-one)
      updateStepStatus("scrape", "processing");
      await new Promise((resolve) => setTimeout(resolve, 2000));
      updateStepStatus("scrape", "complete");

      updateStepStatus("analyze", "processing");
      await new Promise((resolve) => setTimeout(resolve, 3000));
      updateStepStatus("analyze", "complete");

      updateStepStatus("generate", "processing");
      await new Promise((resolve) => setTimeout(resolve, 2000));
      updateStepStatus("generate", "complete");

      updateStepStatus("images", "processing");

      // Make actual API call
      const ideas = await generateAdIdeas({
        company_url: url,
        additional_context: combinedContext || undefined,
      });

      updateStepStatus("images", "complete");

      setAdIdeas(ideas);
      // Fade out ephemeral preface + steps, then append final message
      setMessages((prev) =>
        prev.map((m) => (m.ephemeral ? { ...m, fade: true } : m))
      );
      setTimeout(() => {
        setMessages((prev) => [
          ...prev.filter((m) => !m.ephemeral),
          {
            role: "assistant",
            content: `I've generated 3 ad concepts for ${url}. Select one to continue.`,
          },
        ]);
      }, 500);

      toast.success("Ad ideas generated successfully!");
    } catch (error) {
      console.error("Error generating ad ideas:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to generate ad ideas"
      );
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Sorry, I encountered an error generating ad ideas. Please try again.",
        },
      ]);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSelectIdea = (index: number) => {
    setSelectedIdeaIndex(index);
    const idea = adIdeas[index];
    // Autofill input with "Make this:" + title and description, and route next submit to storyboard
    const combined = `Make this: ${idea.title}. ${idea.description}`;
    setPrefillMessage(combined);
    setRouteNextToStoryboard(true);
    toast.success(`Selected: ${idea.title}`);
    // Remove after 2 secs
    setTimeout(() => {
      toast.dismiss();
    }, 2000);
  };

  const handleGenerateScenes = () => {
    if (!storyboardScenes) return;
    setActiveNav("scenes");
    // For now, just call the backend with storyboard only (assets are stored server-side)
    import("@/utils/api").then(({ generateScenes, API_BASE_URL, websiteToSlug }) => {
      setIsGeneratingScenes(true);
      setGeneratedSceneUrls([]);
      generateScenes(storyboardScenes, companyUrl || undefined)
        .then((res) => {
          // Build default URLs by scene index
          const count: number =
            (res && (res.scenes_generated as number)) ||
            storyboardScenes.length;
          const slug = websiteToSlug(companyUrl);
          const urls = Array.from(
            { length: count },
            (_, i) =>
              `${API_BASE_URL}/generated_scenes/${slug}/images/scene${i + 1}.png`
          );
          setGeneratedSceneUrls(urls);
          toast.success("Scenes generated");
        })
        .catch((err) => {
          // eslint-disable-next-line no-console
          console.error(err);
          toast.error(
            err instanceof Error ? err.message : "Failed to generate scenes"
          );
        })
        .finally(() => {
          setIsGeneratingScenes(false);
        });
    });
  };

  return (
    <div className="flex h-screen bg-background">
      <AppSidebar activeItem={activeNav} onNavigate={handleSidebarNavigate} />
      <div className="flex-1 flex flex-col min-w-0">
        <TopProgressBar
          steps={["Idea", "Storyboard", "Scenes", "Video", "Publish"]}
          activeIndex={
            isGeneratingVideo || isVideoReady
              ? 3
              : storyboardScenes
              ? 1
              : isGeneratingScenes || generatedSceneUrls.length > 0
              ? 2
              : messages.length > 0 ||
                adIdeas.length > 0 ||
                selectedIdeaIndex !== null
              ? 0
              : 0
          }
        />
        {/* Main Content */}
        <main className="flex-1 overflow-y-auto">
          {isGeneratingVideo ? (
            <div className="w-full h-full min-h-[70vh] flex items-center justify-center">
              <div className="flex flex-col items-center gap-4">
                <Loader2 className="h-10 w-10 animate-spin text-foreground" />
                <div className="text-sm text-muted-foreground">
                  Generating your video… this can take a moment.
                </div>
              </div>
            </div>
          ) : activeNav === "drafts" ? (
            <div className="max-w-5xl mx-auto px-6 py-8 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-2xl font-semibold text-foreground">Drafts</h2>
                  <p className="text-sm text-muted-foreground">
                    Load previous storyboards, scenes, and voice overs.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void refreshDrafts()}
                >
                  Refresh
                </Button>
              </div>
              {drafts.length === 0 && !isLoadingDraft && (
                <div className="text-sm text-muted-foreground">
                  No drafts found in generated_scenes.
                </div>
              )}
              {isLoadingDraft && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading draft…
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {drafts.map((draft) => (
                  <button
                    key={draft.slug}
                    type="button"
                    onClick={() => handleDraftSelect(draft.slug)}
                    className="border rounded-lg p-4 text-left hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <div className="font-semibold text-foreground">{draft.slug}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Scenes {draft.scenes} • Voiceovers {draft.voiceovers} • Videos {draft.videos}
                    </div>
                    {draft.final_video && (
                      <div className="text-xs text-green-600 mt-2">
                        Final video available
                      </div>
                    )}
                    {!draft.has_storyboard && (
                      <div className="text-xs text-amber-600 mt-2">
                        Storyboard missing
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ) : activeNav === "storyboard" ? (
            <div className="max-w-5xl mx-auto px-6 py-8 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-2xl font-semibold">Storyboard</h2>
                {storyboardScenes && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleGenerateScenes}
                    disabled={isGeneratingScenes}
                  >
                    Generate scenes
                  </Button>
                )}
              </div>
              {storyboardScenes ? (
                <StoryboardPanel
                  scenes={storyboardScenes}
                  onScenesChange={setStoryboardScenes}
                  onGenerateScenes={handleGenerateScenes}
                  model={storyboardResult?.model}
                  assetsUploader={
                    <div className="mt-2">
                      <CharAssetsUploader
                        assets={charAssets}
                        onAssetsChange={setCharAssets}
                      />
                    </div>
                  }
                />
              ) : (
                <div className="text-sm text-muted-foreground">
                  No storyboard available. Generate a new ad or select a draft.
                </div>
              )}
            </div>
          ) : activeNav === "scenes" ? (
            <div className="max-w-5xl mx-auto px-6 py-8">
              {isGeneratingScenes ? (
                <ScenesGenerationPanel isGenerating={true} sceneUrls={generatedSceneUrls} />
              ) : generatedSceneUrls.length > 0 ? (
                <ScenesGallery
                  imageUrls={generatedSceneUrls}
                  scenes={storyboardScenes || []}
                  onRegenerate={handleRegenerateImage}
                  onCreateVideo={handleCreateVideo}
                  isGeneratingVideo={isGeneratingVideo}
                />
              ) : storyboardScenes ? (
                <div className="flex flex-col gap-4 text-sm text-muted-foreground">
                  <div>No generated scenes yet for this draft.</div>
                  <div>
                    <Button onClick={handleGenerateScenes} disabled={isGeneratingScenes}>
                      Generate scenes
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  No scenes available. Generate a storyboard first or open a draft.
                </div>
              )}
            </div>
          ) : activeNav === "voiceover" ? (
            <div className="max-w-5xl mx-auto px-6 py-8 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-2xl font-semibold">Voice Overs</h2>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleGenerateVoiceovers}
                  disabled={isGeneratingVoiceovers}
                >
                  {isGeneratingVoiceovers ? "Generating..." : "Generate voiceovers"}
                </Button>
              </div>
              {voiceoverUrls.length === 0 ? (
                <div className="text-sm text-muted-foreground">
                  No voiceovers available for this draft yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {voiceoverUrls.map((url, idx) => (
                    <div key={url} className="border rounded-md p-3">
                      <div className="text-sm font-medium text-foreground">Scene {idx + 1}</div>
                      <audio controls src={url} className="w-full mt-2" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : isVideoReady && activeVideoUrl ? (
            <div className="w-full">
              <div className="w-full">
                <div className="w-full">
                  <video
                    ref={videoRef}
                    src={activeVideoUrl}
                    controls
                    className="w-full h-[calc(100vh-110px)] object-contain bg-black"
                  />
                </div>
              </div>
              <div className="max-w-5xl mx-auto px-6 py-4 flex flex-col gap-3">
                {availableVideos.length > 1 && (
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          onClick={handlePrevVideo}
                          disabled={currentVideoIndex === 0}
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          onClick={handleNextVideo}
                          disabled={currentVideoIndex >= availableVideos.length - 1}
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                        <span className="text-sm text-muted-foreground">
                          Video {currentVideoIndex + 1} of {availableVideos.length}
                        </span>
                      </div>
                    </div>
                    <div className="flex gap-3 overflow-x-auto pb-2">
                      {availableVideos.map((url, idx) => (
                        <button
                          key={url}
                          type="button"
                          onClick={() => setCurrentVideoIndex(idx)}
                          className={`border rounded-md overflow-hidden min-w-[160px] ${
                            idx === currentVideoIndex ? "ring-2 ring-primary" : ""
                          }`}
                        >
                          <video
                            src={url}
                            muted
                            loop
                            controls={false}
                            className="w-full h-28 object-cover bg-black"
                          />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="flex flex-wrap gap-3 justify-between">
                  <div className="flex flex-wrap gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleGenerateVoiceovers}
                      disabled={
                        !hasSceneVideos || isGeneratingVoiceovers || isCombiningScenes
                      }
                    >
                      {isGeneratingVoiceovers
                        ? "Generating voiceovers..."
                        : "Generate voiceovers"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={handleCombineScenes}
                      disabled={!hasSceneVideos || isCombiningScenes}
                    >
                      {isCombiningScenes
                        ? "Combining scenes..."
                        : "Combine scenes"}
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleEnterFullscreen}
                    >
                      <span className="mr-2 inline-flex">
                        <Maximize2 className="h-4 w-4" />
                      </span>
                      Fullscreen
                    </Button>
                    <Button type="button" onClick={() => navigate("/publish")}>
                      Continue to Publish
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          ) : isVideoReady ? (
            <div className="w-full h-full min-h-[70vh] flex items-center justify-center">
              <div className="text-sm text-muted-foreground">
                Video generation completed, but no video URL was found.
              </div>
            </div>
          ) : (
            <div className="max-w-5xl mx-auto px-6">
              {isGeneratingScenes ? (
                <ScenesGenerationPanel isGenerating={true} sceneUrls={[]} />
              ) : generatedSceneUrls.length > 0 ? (
                <ScenesGallery
                  imageUrls={generatedSceneUrls}
                  scenes={storyboardScenes || []}
                  onRegenerate={handleRegenerateImage}
                  onCreateVideo={handleCreateVideo}
                  isGeneratingVideo={isGeneratingVideo}
                />
              ) : messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-6">
                  <h2 className="text-4xl font-semibold text-foreground">
                    Generate AI-powered ads
                  </h2>
                  <p className="text-muted-foreground text-lg text-center max-w-2xl">
                    Share your company website and any context. We'll analyze
                    your brand and generate creative ad concepts with visuals.
                  </p>
                  <div className="w-full max-w-3xl">
                    <ChatInput
                      onSend={handleSendMessage}
                      disabled={isProcessing}
                      placeholder="Tell us your website and what kind of ad you want to create..."
                      leftAccessory={
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setShowSources((v) => !v)}
                          className="px-0"
                        >
                          {showSources ? "Hide sources" : "+ Sources"}
                        </Button>
                      }
                    />
                  </div>
                  {showSources && (
                    <div className="w-full max-w-3xl">
                      <SourcesInput sources={sources} onChange={setSources} />
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-8 space-y-6">
                  {messages.map((msg, idx) => (
                    <ChatMessage
                      key={idx}
                      role={msg.role}
                      content={msg.content}
                      typing={msg.typing}
                      fade={msg.fade}
                      steps={msg.ephemeral ? processingSteps : undefined}
                    />
                  ))}

                  {adIdeas.length > 0 && (
                    <AdIdeasGrid
                      ideas={adIdeas}
                      selectedIndex={selectedIdeaIndex}
                      onSelectIdea={handleSelectIdea}
                    />
                  )}

                  {storyboardScenes && !isGeneratingScenes && (
                    <StoryboardPanel
                      scenes={storyboardScenes}
                      onScenesChange={setStoryboardScenes}
                      onGenerateScenes={handleGenerateScenes}
                      model={storyboardResult?.model}
                      assetsUploader={
                        <div className="mt-2">
                          <CharAssetsUploader
                            assets={charAssets}
                            onAssetsChange={setCharAssets}
                          />
                        </div>
                      }
                    />
                  )}

                  {!isGeneratingScenes && generatedSceneUrls.length > 0 && (
                    <ScenesGenerationPanel
                      isGenerating={false}
                      sceneUrls={generatedSceneUrls}
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </main>

        {/* Input Area - hidden when storyboard is present or scenes view is active */}
        {messages.length > 0 &&
          !storyboardScenes &&
          generatedSceneUrls.length === 0 &&
          !isGeneratingScenes &&
          !isGeneratingVideo &&
          !isVideoReady && (
            <div className="border-t border-border bg-background">
              <div className="max-w-5xl mx-auto px-6 py-6">
                <ChatInput
                  onSend={handleSendMessage}
                  disabled={isProcessing}
                  placeholder="Paste your company website URL and any additional context..."
                  prefill={prefillMessage}
                  onVoiceClick={() =>
                    toast.message("Voice input not implemented yet")
                  }
                />
              </div>
            </div>
          )}
      </div>
    </div>
  );
};

export default Index;
