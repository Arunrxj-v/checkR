import { useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Spinner";
import type { Question, QuestionType } from "@/lib/types";

export const QUESTION_TYPES: Array<{ value: QuestionType; label: string }> = [
  { value: "short_answer", label: "Short answer" },
  { value: "long_answer", label: "Long answer" },
  { value: "definition", label: "Definition" },
  { value: "explanation", label: "Explanation" },
  { value: "numerical", label: "Numerical" },
  { value: "programming", label: "Programming" },
  { value: "diagram", label: "Diagram" },
  { value: "essay", label: "Essay" },
  { value: "other", label: "Other" },
];

interface CriterionDraft {
  name: string;
  description: string;
  max_marks: string;
}

export interface QuestionFormValues {
  number: number;
  label: string | null;
  text: string;
  max_marks: number;
  question_type: QuestionType;
  expected_answer: string | null;
  keywords: string[];
  guidance: string | null;
  order_index?: number;
  criteria: Array<{ name: string; description: string | null; max_marks: number }>;
}

const EMPTY_CRITERION: CriterionDraft = { name: "", description: "", max_marks: "" };

interface QuestionFormProps {
  open: boolean;
  onClose: () => void;
  initial?: Question | null;
  defaultNumber: number;
  pending: boolean;
  onSubmit: (values: QuestionFormValues) => void;
}

export function QuestionFormModal({ open, onClose, initial, defaultNumber, pending, onSubmit }: QuestionFormProps) {
  const [number, setNumber] = useState(String(defaultNumber));
  const [text, setText] = useState("");
  const [maxMarks, setMaxMarks] = useState("");
  const [questionType, setQuestionType] = useState<QuestionType>("short_answer");
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [keywords, setKeywords] = useState("");
  const [guidance, setGuidance] = useState("");
  const [criteria, setCriteria] = useState<CriterionDraft[]>([{ ...EMPTY_CRITERION }]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setNumber(String(initial.number));
      setText(initial.text);
      setMaxMarks(String(initial.max_marks));
      setQuestionType(initial.question_type);
      setExpectedAnswer(initial.expected_answer ?? "");
      setKeywords(initial.keywords.join(", "));
      setGuidance(initial.guidance ?? "");
      setCriteria(
        initial.criteria.length
          ? initial.criteria.map((c) => ({
              name: c.name,
              description: c.description ?? "",
              max_marks: String(c.max_marks),
            }))
          : [{ ...EMPTY_CRITERION }],
      );
    } else {
      setNumber(String(defaultNumber));
      setText("");
      setMaxMarks("");
      setQuestionType("short_answer");
      setExpectedAnswer("");
      setKeywords("");
      setGuidance("");
      setCriteria([{ ...EMPTY_CRITERION }]);
    }
    setError(null);
  }, [open, initial, defaultNumber]);

  const criteriaTotal = useMemo(
    () => criteria.reduce((sum, c) => sum + (Number(c.max_marks) || 0), 0),
    [criteria],
  );

  const updateCriterion = (index: number, patch: Partial<CriterionDraft>) =>
    setCriteria((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const max = Number(maxMarks);
    if (!text.trim()) return setError("Question text is required.");
    if (!Number.isFinite(max) || max <= 0) return setError("Maximum marks must be greater than zero.");

    const cleaned = criteria
      .filter((c) => c.name.trim())
      .map((c) => ({
        name: c.name.trim(),
        description: c.description.trim() || null,
        max_marks: Number(c.max_marks) || 0,
      }));
    if (cleaned.length > 0) {
      const total = cleaned.reduce((sum, c) => sum + c.max_marks, 0);
      if (Math.abs(total - max) > 0.01) {
        return setError(
          `Marking criteria total ${total.toFixed(1)} must equal the question's maximum of ${max.toFixed(1)}.`,
        );
      }
    }
    setError(null);
    onSubmit({
      number: Number(number) || defaultNumber,
      label: `Q${Number(number) || defaultNumber}`,
      text: text.trim(),
      max_marks: max,
      question_type: questionType,
      expected_answer: expectedAnswer.trim() || null,
      keywords: keywords
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean),
      guidance: guidance.trim() || null,
      criteria: cleaned,
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={initial ? `Edit question ${initial.label ?? initial.number}` : "Add question"}
      description="Define the question and the criteria-level marking scheme the AI must score against."
      width="max-w-3xl"
      footer={
        <>
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="question-form" className="btn-primary px-space-md py-1.5  text-label-md" disabled={pending}>
            {pending ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : null}
            {initial ? "Save changes" : "Add question"}
          </button>
        </>
      }
    >
      <form id="question-form" onSubmit={submit} className="flex flex-col gap-space-md">
        <div className="grid grid-cols-[80px_1fr_120px_160px] gap-space-md">
          <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
            No.
            <input className="field font-mono" type="number" min={1} max={999} value={number} onChange={(e) => setNumber(e.target.value)} required />
          </label>
          <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
            Marks
            <input className="field font-mono" type="number" min={0} step="0.5" value={maxMarks} onChange={(e) => setMaxMarks(e.target.value)} required />
          </label>
          <label className="col-span-2 flex flex-col gap-1  text-label-md text-on-surface-variant">
            Type
            <select className="field" value={questionType} onChange={(e) => setQuestionType(e.target.value as QuestionType)}>
              {QUESTION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Question text
          <textarea className="field" rows={2} value={text} onChange={(e) => setText(e.target.value)} required placeholder="Explain AVL tree balancing rotations and show their time complexity derivation." />
        </label>

        <div className="grid grid-cols-2 gap-space-md">
          <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
            Expected answer (reference)
            <textarea className="field" rows={3} value={expectedAnswer} onChange={(e) => setExpectedAnswer(e.target.value)} placeholder="A model answer the AI can anchor to." />
          </label>
          <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
            Guidance to the evaluator
            <textarea className="field" rows={3} value={guidance} onChange={(e) => setGuidance(e.target.value)} placeholder="Accept alternative correct derivations." />
          </label>
        </div>

        <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
          Keywords (comma separated)
          <input className="field" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="balance factor, rotation, O(log n)" />
        </label>

        <div className="rounded-lg border border-outline-variant">
          <div className="flex items-center justify-between border-b border-outline-variant bg-surface-container-low px-space-md py-space-sm">
            <span className=" text-label-md font-semibold uppercase tracking-wider text-primary">
              Marking criteria
            </span>
            <span className={`font-mono text-label-sm ${criteriaTotal === Number(maxMarks) ? "text-verified-fg" : "text-review-fg"}`}>
              Σ {criteriaTotal.toFixed(1)} / {Number(maxMarks || 0).toFixed(1)}
            </span>
          </div>
          <div className="flex flex-col divide-y divide-outline-variant">
            {criteria.map((criterion, index) => (
              <div key={index} className="grid grid-cols-[1fr_1.4fr_90px_32px] items-center gap-space-sm px-space-md py-space-sm">
                <input className="field" placeholder="Criterion name" value={criterion.name} onChange={(e) => updateCriterion(index, { name: e.target.value })} />
                <input className="field" placeholder="What earns these marks" value={criterion.description} onChange={(e) => updateCriterion(index, { description: e.target.value })} />
                <input className="field font-mono" type="number" min={0} step="0.5" placeholder="0" value={criterion.max_marks} onChange={(e) => updateCriterion(index, { max_marks: e.target.value })} />
                <button
                  type="button"
                  aria-label="Remove criterion"
                  className="flex h-7 w-7 items-center justify-center rounded text-outline transition-colors hover:bg-critical-bg hover:text-critical"
                  onClick={() => setCriteria((prev) => (prev.length === 1 ? prev : prev.filter((_, i) => i !== index)))}
                >
                  <Icon name="delete" className="text-[16px]" />
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="flex w-full items-center justify-center gap-space-xs border-t border-outline-variant py-1.5  text-label-md text-secondary transition-colors hover:bg-surface-container-low"
            onClick={() => setCriteria((prev) => [...prev, { ...EMPTY_CRITERION }])}
          >
            <Icon name="add" className="text-[16px]" /> Add criterion
          </button>
        </div>

        {error ? (
          <p className="flex items-center gap-space-xs rounded border border-critical-border bg-critical-bg px-space-sm py-1.5  text-body-sm text-critical-fg">
            <Icon name="error" className="text-[16px]" />
            {error}
          </p>
        ) : null}
      </form>
    </Modal>
  );
}
