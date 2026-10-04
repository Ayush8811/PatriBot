import type { Metadata } from "next";

import { ChatView } from "./chat-view";

export const metadata: Metadata = { title: "Ask PatriBot" };

export default function ChatPage() {
  return <ChatView />;
}
