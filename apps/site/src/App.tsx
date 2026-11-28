import { Developers } from "./Developers.tsx";
import { Features } from "./Features.tsx";
import { Hero } from "./Hero.tsx";
import { HowItWorks } from "./HowItWorks.tsx";
import { Page } from "./Page.tsx";
import { QuickStart } from "./QuickStart.tsx";

/** The marketing page: one scrolling page in the app's own look. */
export function App() {
  return (
    <Page page="home">
      <Hero />
      <Features />
      <HowItWorks />
      <Developers />
      <QuickStart />
    </Page>
  );
}
