/** Live paper preview — the form rendered as a Government Resolution page,
 * updating on every keystroke. This is a faithful CSS approximation for
 * editing flow; the downloadable PDF comes from the calibrated renderer. */
import type { GRForm } from "../lib/types";

const DEV = "०१२३४५६७८९";
const toDev = (s: string) => s.replace(/[0-9]/g, (d) => DEV[Number(d)]);

const MONTHS_MR = ["जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून",
  "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"];
const MONTHS_EN = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

function fmtDate(iso: string | undefined, mr: boolean): string {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  const s = `${d.getDate()} ${(mr ? MONTHS_MR : MONTHS_EN)[d.getMonth()]}, ${d.getFullYear()}`;
  return mr ? toDev(s) : s;
}

export interface PaperTable {
  after_clause: number;
  headers: string[];
  rows: string[][];
}

export function GRPaper({ form, tables }: { form: GRForm; tables: PaperTable[] }) {
  const mr = form.lang !== "en";
  const T = (s: string) => (mr ? toDev(s) : s);
  const clauses = form.clauses ?? [];
  const refs = (form.references ?? []).map((r) => (typeof r === "string" ? r : r.text));
  const blank = (s: string) =>
    s.split("____").flatMap((part, i) =>
      i === 0 ? [part] : [<mark key={i} className="rounded bg-warn-soft px-1 font-bold text-warn">____</mark>, part]);

  return (
    <div
      className="mx-auto w-full max-w-[560px] rounded-sm border border-line bg-white px-10 py-8 text-[12.5px] leading-[1.9] text-black shadow-card"
      style={{ fontFamily: '"Mukta","Noto Sans Devanagari",sans-serif' }}
    >
      {/* subject block — top right, bold, ruled */}
      <div className="ml-auto w-[62%] border-b border-black pb-1 text-justify font-bold">
        {blank(T(form.subject || (mr ? "…बाबत." : "Subject.")))}
      </div>

      {/* letterhead */}
      <div className="mt-3 text-center font-bold leading-relaxed">
        <div className="text-[14px]">{mr ? "महाराष्ट्र शासन" : "GOVERNMENT OF MAHARASHTRA"}</div>
        <div>{T(form.department || "")}</div>
        <div>
          {mr ? "शासन निर्णय क्रमांक:- " : "Government Resolution No.: "}
          {T(form.gr_number || "")}
        </div>
        <div>{mr ? "मादाम कामा रोड, हुतात्मा राजगुरु चौक," : "Madam Cama Road, Hutatma Rajguru Chowk,"}</div>
        <div>{mr ? "मंत्रालय, मुंबई - ४०० ०३२." : "Mantralaya, Mumbai - 400 032."}</div>
        <div>{mr ? "दिनांक: " : "Date: "}{fmtDate(form.date as string, mr)}</div>
      </div>

      {/* वाचा */}
      {refs.length > 0 && (
        <div className="mt-3">
          <span className="font-bold">{mr ? "वाचा :-" : "Read :-"}</span>
          <ol className="ml-10 list-none">
            {refs.map((r, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0">{T(`${i + 1})`)}</span>
                <span className="text-[11.5px]">{T(r)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* प्रस्तावना */}
      <div className="mt-3 font-bold">{mr ? "प्रस्तावना :-" : "Preamble :-"}</div>
      <p className="text-justify indent-8">{blank(T(form.background || ""))}</p>

      {/* शासन निर्णय + clauses + tables */}
      <div className="mt-3 font-bold">{mr ? "शासन निर्णय :-" : "Government Resolution :-"}</div>
      {clauses.map((c, i) => (
        <div key={i}>
          <div className="flex gap-2">
            <span className="shrink-0">{T(`${i + 1}.`)}</span>
            <p className="flex-1 text-justify">{blank(T(c))}</p>
          </div>
          {tables.filter((t) => t.after_clause === i + 1).map((t, j) => (
            <table key={j} className="my-2 w-full border-collapse text-[11px]">
              {t.headers.length > 0 && (
                <thead>
                  <tr>{t.headers.map((h, k) => (
                    <th key={k} className="border border-black bg-paper px-1.5 py-0.5 font-bold">{T(h)}</th>
                  ))}</tr>
                </thead>
              )}
              <tbody>
                {t.rows.map((row, k) => (
                  <tr key={k}>{row.map((cell, m) => (
                    <td key={m} className="border border-black px-1.5 py-0.5">{T(cell)}</td>
                  ))}</tr>
                ))}
              </tbody>
            </table>
          ))}
        </div>
      ))}
      <div className="flex gap-2">
        <span className="shrink-0">{T(`${clauses.length + 1}.`)}</span>
        <p className="flex-1 text-justify text-[11.5px] text-black/70">
          {mr
            ? <>सदर शासन निर्णय महाराष्ट्र शासनाच्या <span className="text-blue-700 underline">www.maharashtra.gov.in</span> या संकेतस्थळावर उपलब्ध…</>
            : <>This Government Resolution is available on <span className="text-blue-700 underline">www.maharashtra.gov.in</span>…</>}
        </p>
      </div>

      {/* signature */}
      <div className="mt-4 text-center">
        {mr ? "महाराष्ट्राचे राज्यपाल यांच्या आदेशानुसार व नावाने." : "By order and in the name of the Governor of Maharashtra."}
      </div>
      <div className="mr-4 mt-10 text-right">
        <div className="font-bold">( {T(form.signatory || "")} )</div>
        <div>{T(form.designation || "")}{mr ? ", महाराष्ट्र शासन" : ", Government of Maharashtra"}</div>
      </div>

      <div className="mt-4 border-t border-line pt-1 text-center text-[10px] text-black/40">
        {mr ? "पूर्वदृश्य — अंतिम PDF अस्सल शासकीय रेंडररने तयार होते" : "Preview — the final PDF comes from the calibrated authentic renderer"}
      </div>
    </div>
  );
}
