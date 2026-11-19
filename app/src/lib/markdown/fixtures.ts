export const completeFixture = String.raw`## Understanding change
A single newline stays visible.
The teacher asks **why**, then follows your reasoning.

中文**「重点」**。日本語**「大切」**。한국어**「중요」**.
https://example.com。后续

The map $f(x)=x^2$ is smooth. Legacy \(a<b\) works. A price: $5.

\[\int_0^1 x^2\,dx = \frac{1}{3}\]

| Idea | Example |
|---|---|
| Rate | $2x$ |

- [x] Recognize change
- [ ] Explain the derivative

> [!NOTE]
> Explain the idea in your own words.

~~~typescript startLine=7
const rate = (x: number) => 2 * x;
~~~

~~~mermaid
graph LR
  A[Observe] --> B[Explain]
  B --> C[Practice]
~~~

[Reference](https://example.com) ![remote](https://example.com/image.png)
`;
export const streamingFixture = '**Building an idea**\n\n$a<b$ and **a partial explanation';
