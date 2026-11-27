### haiku
|                           | feature-flags-fixture | spring-petclinic-microservices |
|---------------------------|----------------------:|-------------------------------:|
| Claude calls              |                     8 |                              8 |
| API calls                 |                     8 |                              8 |
| Cache hits                |                     0 |                              0 |
| Failed calls              |                     0 |                              0 |
| Input tokens              |                 1,840 |                          2,148 |
| Output tokens             |                 2,120 |                          2,179 |
| Cache read tokens         |                15,664 |                         13,706 |
| Cache write tokens        |                     0 |                          1,958 |
| Spent (USD)               |             $0.001402 |                      $0.001686 |
| Saved by cache (USD)      |             $0.000000 |                      $0.000000 |
| Candidates sent to Claude |                     8 |                              8 |
| Cost per candidate (USD)  |             $0.000175 |                      $0.000211 |
| Confirmed by Claude       |                     8 |                              8 |
| Cost per confirmed (USD)  |             $0.000175 |                      $0.000211 |
| Precision                 |            1.00 (8/8) |                     1.00 (8/8) |
| Recall                    |            1.00 (8/8) |                    0.24 (8/33) |

### sonnet
|                           | feature-flags-fixture | spring-petclinic-microservices |
|---------------------------|----------------------:|-------------------------------:|
| Claude calls              |                     8 |                              8 |
| API calls                 |                     8 |                              8 |
| Cache hits                |                     0 |                              0 |
| Failed calls              |                     0 |                              0 |
| Input tokens              |                 1,840 |                          2,148 |
| Output tokens             |                 1,907 |                          2,055 |
| Cache read tokens         |                15,664 |                         13,706 |
| Cache write tokens        |                     0 |                          1,958 |
| Spent (USD)               |             $0.024318 |                      $0.031113 |
| Saved by cache (USD)      |             $0.000000 |                      $0.000000 |
| Candidates sent to Claude |                     8 |                              8 |
| Cost per candidate (USD)  |             $0.003040 |                      $0.003889 |
| Confirmed by Claude       |                     8 |                              8 |
| Cost per confirmed (USD)  |             $0.003040 |                      $0.003889 |
| Precision                 |            1.00 (8/8) |                     1.00 (8/8) |
| Recall                    |            1.00 (8/8) |                    0.24 (8/33) |

