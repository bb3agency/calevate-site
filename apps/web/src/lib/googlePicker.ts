/**
 * Google's file picker, restricted to spreadsheets (D-703).
 *
 * The owner picks a spreadsheet on their own Google account; with the `drive.file` scope
 * that pick is what shares the file with Calevate. The access token, browser key and app id
 * (the Cloud project number) come from `POST /v1/integrations/google-sheets/{id}/picker`.
 * The loader and builder calls follow developers.google.com/workspace/drive/picker/guides/
 * web-picker (read 10 Oct 2026); `setAppId` must be the same project as the OAuth client.
 */

const LOADER_SRC = "https://apis.google.com/js/api.js";

export interface PickedSheet {
  id: string;
  name: string;
  url: string;
}

interface PickerDoc {
  id: string;
  name?: string;
  url?: string;
}

interface PickerResponse {
  action: string;
  docs?: PickerDoc[];
}

interface PickerBuilder {
  addView(view: unknown): PickerBuilder;
  setOAuthToken(token: string): PickerBuilder;
  setDeveloperKey(key: string): PickerBuilder;
  setAppId(id: string): PickerBuilder;
  setCallback(cb: (data: PickerResponse) => void): PickerBuilder;
  setTitle(title: string): PickerBuilder;
  build(): { setVisible(visible: boolean): void };
}

interface GooglePickerNamespace {
  PickerBuilder: new () => PickerBuilder;
  DocsView: new (viewId: unknown) => { setMode(mode: unknown): unknown };
  ViewId: { SPREADSHEETS: unknown };
  DocsViewMode: { LIST: unknown };
  Action: { PICKED: string; CANCEL: string };
}

declare global {
  interface Window {
    gapi?: { load(name: string, cb: { callback: () => void; onerror: () => void }): void };
    google?: { picker?: GooglePickerNamespace };
  }
}

let loading: Promise<GooglePickerNamespace> | null = null;

function loadPicker(): Promise<GooglePickerNamespace> {
  if (window.google?.picker) return Promise.resolve(window.google.picker);
  if (loading) return loading;
  loading = new Promise<GooglePickerNamespace>((resolve, reject) => {
    const fail = () => {
      loading = null;
      reject(new Error("Google's file picker could not be loaded."));
    };
    const ready = () => {
      if (!window.gapi) return fail();
      window.gapi.load("picker", {
        callback: () => (window.google?.picker ? resolve(window.google.picker) : fail()),
        onerror: fail,
      });
    };
    if (window.gapi) return ready();
    const script = document.createElement("script");
    script.src = LOADER_SRC;
    script.async = true;
    script.onload = ready;
    script.onerror = fail;
    document.head.appendChild(script);
  });
  return loading;
}

/** Open the picker; resolves with the chosen spreadsheet, or null when cancelled. */
export async function pickSpreadsheet(config: {
  accessToken: string;
  developerKey: string;
  appId: string;
}): Promise<PickedSheet | null> {
  const picker = await loadPicker();
  return new Promise<PickedSheet | null>((resolve) => {
    // LIST mode: thumbnails need a broader scope than `drive.file` (web-picker guide).
    const view = new picker.DocsView(picker.ViewId.SPREADSHEETS);
    view.setMode(picker.DocsViewMode.LIST);
    new picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(config.accessToken)
      .setDeveloperKey(config.developerKey)
      .setAppId(config.appId)
      .setTitle("Choose a spreadsheet")
      .setCallback((data) => {
        if (data.action === picker.Action.PICKED && data.docs?.[0]) {
          const doc = data.docs[0];
          resolve({ id: doc.id, name: doc.name ?? "Spreadsheet", url: doc.url ?? "" });
        } else if (data.action === picker.Action.CANCEL) {
          resolve(null);
        }
      })
      .build()
      .setVisible(true);
  });
}
