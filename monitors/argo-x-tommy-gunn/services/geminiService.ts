
import { GoogleGenAI, Type } from "@google/genai";
import { HardeningReport, MusicIntentResult } from "../types";

const apiKey = import.meta.env.VITE_GEMINI_API_KEY as string | undefined;
const ai = apiKey ? new GoogleGenAI({ apiKey }) : null;

export const analyzeArgoCode = async (codeContext: string): Promise<HardeningReport> => {
  if (!ai) {
    throw new Error("Missing VITE_GEMINI_API_KEY");
  }
  const prompt = `
    As a Lead Systems Architect, audit the Argo Music Migration.
    
    Context:
    ${codeContext}
    
    CONSTRAINTS TO ENFORCE:
    1. NO ORMs: Code must use raw sqlite3 only.
    2. DETERMINISTIC LOOKUP: LLM is for parsing intent, SQL is for finding the file.
    3. AUDIO OWNERSHIP: Verify music playback suspends TTS and claims output lock.
    4. NO GUESSING: If SQL returns 0 results, return "Not Found" - do not let LLM hallucinate metadata.
    5. DATA INTEGRITY: Ensure data/music.db directory is validated.

    Return a JSON report following the standard HardeningReport schema.
  `;

  const response = await ai.models.generateContent({
    model: 'gemini-3-pro-preview',
    contents: prompt,
    config: {
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          overallScore: { type: Type.NUMBER },
          bottlenecks: { type: Type.ARRAY, items: { type: Type.STRING } },
          architecturalRisks: { type: Type.ARRAY, items: { type: Type.STRING } },
          recommendations: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                title: { type: Type.STRING },
                description: { type: Type.STRING },
                impact: { type: Type.STRING, enum: ['High', 'Medium', 'Low'] },
                category: { type: Type.STRING, enum: ['Security', 'Performance', 'Stability'] },
                codeSnippet: { type: Type.STRING }
              },
              required: ['title', 'description', 'impact', 'category']
            }
          }
        },
        required: ['overallScore', 'bottlenecks', 'recommendations', 'architecturalRisks']
      }
    }
  });

  return JSON.parse(response.text || "{}") as HardeningReport;
};

export const testMusicIntent = async (query: string): Promise<MusicIntentResult> => {
  if (!ai) {
    throw new Error("Missing VITE_GEMINI_API_KEY");
  }
  const prompt = `
    Argo Music Engine simulation. 
    User: "${query}"
    
    Identify metadata (Artist, Song, Genre, Era).
    Determine systemAction:
    - If found in hypothetical SQL: "Playing {song} by {artist} from {year}."
    - If not found: "I couldn't find that in your Jellyfin library."
  `;

  const response = await ai.models.generateContent({
    model: 'gemini-3-flash-preview',
    contents: prompt,
    config: {
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          artist: { type: Type.STRING, nullable: true },
          song: { type: Type.STRING, nullable: true },
          genre: { type: Type.STRING, nullable: true },
          era: { type: Type.STRING, nullable: true },
          confidence: { type: Type.NUMBER },
          systemAction: { type: Type.STRING },
          lookupMethod: { type: Type.STRING, enum: ['SQL_DETERMINISTIC', 'NOT_FOUND'] }
        },
        required: ['artist', 'song', 'genre', 'era', 'confidence', 'systemAction', 'lookupMethod']
      }
    }
  });

  return JSON.parse(response.text || "{}") as MusicIntentResult;
};
