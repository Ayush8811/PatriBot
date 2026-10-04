import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TrainView } from "./train-view";

export async function generateMetadata({ params }: PageProps<"/trains/[trainNo]">): Promise<Metadata> {
  const { trainNo } = await params;
  return { title: `Train ${trainNo}` };
}

export default async function TrainPage({ params }: PageProps<"/trains/[trainNo]">) {
  const { trainNo } = await params;
  if (!/^\d{4,5}$/.test(trainNo)) notFound();
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:py-8">
      <TrainView trainNo={trainNo} />
    </div>
  );
}
